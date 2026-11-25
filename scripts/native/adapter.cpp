#include <windows.h>
#include <MinHook.h>
#include <array>
#include <algorithm>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <unordered_map>

#include "nod_layout.hpp"
#include "forward_metadata.hpp"

namespace {
static_assert(sizeof(void*) == 4, "Nod adapter is x86 only");
using Measure = int (__cdecl*)(const void*, const char*);
using Width = int (__cdecl*)(const void*, unsigned);
using Draw = void (__thiscall*)(void*, int, int, const char*, int, int, int, int);
using Line = void (__thiscall*)(void*, const char*);
Measure original_measure;
Draw original_draw16, original_draw32;
Line original_wrap;
std::uintptr_t base;
std::filesystem::path data_path;
std::vector<unsigned char> glyph_data;
std::array<std::unordered_map<std::uint32_t, std::size_t>, 3> glyph_offsets;
constexpr std::array<int, 3> cells{10, 15, 20};
constexpr std::size_t max_string = 32768;

template<class T>
T field(const void* ptr, std::size_t offset) {
    T result;
    std::memcpy(&result, static_cast<const unsigned char*>(ptr) + offset, sizeof(T));
    return result;
}

void log(const char* message) {
    std::ofstream stream(data_path / L"adapter.log", std::ios::app);
    stream << message << '\n';
}

void load_glyphs() {
    std::ifstream stream(data_path / L"glyphs.bin", std::ios::binary);
    glyph_data.assign(std::istreambuf_iterator<char>(stream), {});
    if (glyph_data.size() < 16 || std::memcmp(glyph_data.data(), "NODZHGL2", 8))
        throw std::runtime_error("Invalid glyph table header");
    const auto count = field<std::uint32_t>(glyph_data.data(), 8);
    if (!count || count > 10000 || field<std::uint32_t>(glyph_data.data(), 12) != cells.size())
        throw std::runtime_error("Invalid glyph table counts");
    std::size_t offset = 16;
    for (std::size_t profile = 0; profile < cells.size(); ++profile) {
        const auto side = static_cast<std::size_t>(cells[profile]);
        if (glyph_data.size() - offset < 4 + count * (4 + side * side) ||
            field<std::uint32_t>(glyph_data.data(), offset) != side)
            throw std::runtime_error("Invalid glyph table profile");
        offset += 4;
        for (unsigned i = 0; i < count; ++i) {
            const auto code = field<std::uint32_t>(glyph_data.data(), offset);
            offset += 4;
            if (code < 128 || code > 0x10ffff || !glyph_offsets[profile].emplace(code, offset).second)
                throw std::runtime_error("Invalid glyph table code point");
            offset += side * side;
        }
    }
    if (offset != glyph_data.size()) throw std::runtime_error("Trailing glyph data");
}

std::size_t profile_for(const void* font) {
    const int height = font ? field<int>(font, 0) : 10;
    return height >= 18 ? 2 : height >= 13 ? 1 : 0;
}

bool localized(const char* input, std::vector<nodzh::Character>& chars, std::string_view& text) {
    if (!input) return false;
    const std::size_t length = strnlen_s(input, max_string);
    if (!length || length >= max_string) return false;
    text = {input, length};
    if (std::none_of(text.begin(), text.end(), [](unsigned char ch) { return ch >= 128; }))
        return false;
    if (!nodzh::decode(text, chars)) return false;
    return std::all_of(chars.begin(), chars.end(), [](const auto& ch) {
        return ch.code < 128 || glyph_offsets[0].find(ch.code) != glyph_offsets[0].end();
    });
}

int advance(const void* font, std::size_t profile, std::uint32_t code) {
    if (code >= 128) return cells[profile];
    const auto width = reinterpret_cast<Width>(base + 0xca430);
    return (std::max)(0, width(font, code));
}

int __cdecl measure(const void* font, const char* input) {
    try {
        std::vector<nodzh::Character> chars;
        std::string_view text;
        const bool accepted = font && localized(input, chars, text);
        if (accepted) {
            int width = 0;
            const auto profile = profile_for(font);
            for (const auto& ch : chars) width += advance(font, profile, ch.code);
            return width;
        }
    } catch (...) {}
    return original_measure(font, input);
}

void __fastcall wrap_line(void* entry, void*, const char* input) {
    try {
        std::vector<nodzh::Character> chars;
        std::string_view text;
        const auto* widget = field<void*>(entry, 0x30);
        if (widget && (field<unsigned char>(widget, 0x2d8) & 4) && localized(input, chars, text)) {
            const auto* font = field<void*>(widget, 0x2d4);
            const int width = field<int>(entry, 0x20);
            if (font && width > 0) {
                const auto profile = profile_for(font);
                const auto parts = nodzh::wrap(text, chars, width, [&](std::uint32_t code) {
                    return advance(font, profile, code);
                });
                std::vector<std::string> lines(parts.begin(), parts.end());
                const auto append = reinterpret_cast<Line>(base + 0xd5c80);
                for (const auto& line : lines) append(entry, line.c_str());
                return;
            }
        }
    } catch (...) {}
    original_wrap(entry, input);
}

void draw(Draw original, void* surface, int x, int y, const char* input,
          int alpha, int red, int green, int blue) {
    try {
        std::vector<nodzh::Character> chars;
        std::string_view text;
        auto& selected_font = *reinterpret_cast<const void**>(base + 0x2e50d8);
        const auto* font = selected_font;
        const bool accepted = surface && font && localized(input, chars, text);
        if (accepted) {
            const auto profile = profile_for(font);
            const int side = cells[profile];
            // A temporary one-glyph view uses the native blitter, palette and clipping.
            constexpr unsigned slot = 'W';
            constexpr unsigned metrics = 2 + 6 * slot;
            std::array<std::uint32_t, 0x1834 / 4> one_glyph{};
            one_glyph[0] = field<std::uint32_t>(font, 0);
            one_glyph[1] = side;
            one_glyph[metrics + 1] = field<std::uint32_t>(font, 8 + slot * 24 + 4);
            one_glyph[metrics + 2] = side;
            one_glyph[metrics + 3] = side;
            one_glyph[metrics + 4] = side;
            one_glyph[0x1830 / 4] = side;
            for (const auto& ch : chars) {
                if (ch.code < 128) {
                    const char latin[] = {static_cast<char>(ch.code), '\0'};
                    original(surface, x, y, latin, alpha, red, green, blue);
                } else {
                    const auto* bitmap = glyph_data.data() + glyph_offsets[profile].at(ch.code);
                    one_glyph[0x1808 / 4] = reinterpret_cast<std::uintptr_t>(bitmap);
                    selected_font = one_glyph.data();
                    original(surface, x, y, "W", alpha, red, green, blue);
                    selected_font = font;
                }
                x += advance(font, profile, ch.code);
            }
            return;
        }
    } catch (...) {}
    original(surface, x, y, input, alpha, red, green, blue);
}

void __fastcall draw16(void* surface, void*, int x, int y, const char* input,
                       int alpha, int red, int green, int blue) {
    draw(original_draw16, surface, x, y, input, alpha, red, green, blue);
}

void __fastcall draw32(void* surface, void*, int x, int y, const char* input,
                       int alpha, int red, int green, int blue) {
    draw(original_draw32, surface, x, y, input, alpha, red, green, blue);
}

struct Entry {
    std::uintptr_t rva;
    const char* bytes;
    void* hook;
    void** trampoline;
};

const Entry entries[] = {
    {0xca3f0, "\x8b\x54\x24\x08\x33\xc0\x8a\x0a", reinterpret_cast<void*>(measure), reinterpret_cast<void**>(&original_measure)},
    {0xca470, "\x83\xec\x18\x66\x0f\xb6\x54\x24", reinterpret_cast<void*>(draw16), reinterpret_cast<void**>(&original_draw16)},
    {0xca720, "\x83\xec\x18\x53\x55\x56\x8b\x5c", reinterpret_cast<void*>(draw32), reinterpret_cast<void**>(&original_draw32)},
    {0xd5d30, "\x51\x56\x8b\x74\x24\x0c\x85\xf6", reinterpret_cast<void*>(wrap_line), reinterpret_cast<void**>(&original_wrap)},
};

bool ready() {
    return std::all_of(std::begin(entries), std::end(entries), [](const Entry& entry) {
        return !std::memcmp(reinterpret_cast<const void*>(base + entry.rva), entry.bytes, 8);
    });
}

DWORD WINAPI initialize(void*) {
    try {
        wchar_t name[MAX_PATH]{};
        const auto length = GetModuleFileNameW(nullptr, name, MAX_PATH);
        if (!length || length >= MAX_PATH) return 0;
        const std::filesystem::path exe(name);
        if (_wcsicmp(exe.filename().c_str(), L"Vampire.exe")) return 0;
        data_path = exe.parent_path() / L"NodChinese";
        if (!std::filesystem::exists(data_path / L"glyphs.bin") ||
            std::filesystem::exists(data_path / L"disabled.flag")) return 0;
        base = reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        for (int attempt = 0; attempt < 600 && !ready(); ++attempt) Sleep(25);
        if (!ready() || std::memcmp(reinterpret_cast<const void*>(base + 0xca430), "\x8b\x44\x24\x08\x3c\xff", 6) ||
            std::memcmp(reinterpret_cast<const void*>(base + 0xd5c80), "\x53\x55\x56\x8b\xe9\x6a", 6)) {
            log("runtime signatures differ; adapter disabled");
            return 0;
        }
        load_glyphs();
        if (MH_Initialize() != MH_OK) throw std::runtime_error("MinHook initialization failed");
        for (const auto& entry : entries) {
            auto* target = reinterpret_cast<void*>(base + entry.rva);
            if (MH_CreateHook(target, entry.hook, entry.trampoline) != MH_OK || MH_QueueEnableHook(target) != MH_OK) {
                MH_Uninitialize();
                throw std::runtime_error("Unable to prepare Nod font hook");
            }
        }
        if (MH_ApplyQueued() != MH_OK) {
            MH_Uninitialize();
            throw std::runtime_error("Unable to enable Nod font hooks");
        }
        log("Nod UTF-8 measure, wrap and draw hooks enabled");
    } catch (const std::exception& error) { log(error.what()); }
    return 0;
}

INIT_ONCE real_once = INIT_ONCE_STATIC_INIT;
BOOL CALLBACK load_winmm(PINIT_ONCE, void*, void**);
}  // namespace

extern "C" FARPROC g_forwards[NODZH_FORWARD_COUNT] = {};

namespace {
BOOL CALLBACK load_winmm(PINIT_ONCE, void*, void**) {
    wchar_t system[MAX_PATH]{};
    const auto length = GetSystemWow64DirectoryW(system, MAX_PATH);
    if (!length || length >= MAX_PATH) return FALSE;
    const auto path = std::filesystem::path(system) / L"winmm.dll";
    const auto module = LoadLibraryExW(path.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    HMODULE proxy = nullptr;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       reinterpret_cast<LPCWSTR>(&load_winmm), &proxy);
    if (!module || module == proxy) return FALSE;
    for (unsigned i = 0; i < NODZH_FORWARD_COUNT; ++i) {
        const auto* name = forward_names[i] ? forward_names[i] : MAKEINTRESOURCEA(forward_ordinals[i]);
        g_forwards[i] = GetProcAddress(module, name);
    }
    return TRUE;
}
}  // namespace

extern "C" void __cdecl resolve_forward(unsigned index) {
    if (index >= NODZH_FORWARD_COUNT ||
        !InitOnceExecuteOnce(&real_once, load_winmm, nullptr, nullptr) || !g_forwards[index])
        ExitProcess(ERROR_PROC_NOT_FOUND);
}

#include "forward_stubs.inc"

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, void*) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        if (const auto worker = CreateThread(nullptr, 0, initialize, nullptr, 0, nullptr)) CloseHandle(worker);
    }
    return TRUE;
}
