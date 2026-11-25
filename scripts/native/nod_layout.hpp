#pragma once

#include <cstdint>
#include <string_view>
#include <vector>

namespace nodzh {

struct Character {
    std::uint32_t code;
    std::size_t begin;
    std::size_t end;
};

inline bool decode(std::string_view text, std::vector<Character>& result) {
    result.clear();
    for (std::size_t pos = 0; pos < text.size();) {
        const std::size_t begin = pos;
        const auto lead = static_cast<unsigned char>(text[pos++]);
        std::uint32_t code = lead;
        if (lead >= 0x80) {
            unsigned remaining;
            std::uint32_t minimum;
            if (lead >= 0xc2 && lead <= 0xdf) {
                code = lead & 0x1fu;
                remaining = 1;
                minimum = 0x80;
            } else if (lead >= 0xe0 && lead <= 0xef) {
                code = lead & 0x0fu;
                remaining = 2;
                minimum = 0x800;
            } else if (lead >= 0xf0 && lead <= 0xf4) {
                code = lead & 0x07u;
                remaining = 3;
                minimum = 0x10000;
            } else {
                return false;
            }
            if (remaining > text.size() - pos) return false;
            while (remaining--) {
                const auto byte = static_cast<unsigned char>(text[pos++]);
                if ((byte & 0xc0u) != 0x80u) return false;
                code = (code << 6) | (byte & 0x3fu);
            }
            if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return false;
        }
        result.push_back({code, begin, pos});
    }
    return true;
}

inline bool space(std::uint32_t code) {
    return code == ' ' || code == '\t' || code == 0x00a0 || code == 0x3000;
}

inline bool word_boundary(std::uint32_t left, std::uint32_t right) {
    constexpr std::u32string_view closing = U",.!?:;)]}，。！？：；、）》」』】”’";
    constexpr std::u32string_view opening = U"([{（《「『【“‘";
    if (closing.find(static_cast<char32_t>(right)) != std::u32string_view::npos ||
        opening.find(static_cast<char32_t>(left)) != std::u32string_view::npos) return false;
    return space(left) || space(right) || left > 0x7f || right > 0x7f;
}

template<class Advance>
std::vector<std::string_view> wrap(std::string_view text, const std::vector<Character>& characters,
                                  int width, Advance advance) {
    std::vector<std::string_view> lines;
    if (characters.empty() || width <= 0) return {text};
    std::size_t start = 0;
    while (start < characters.size()) {
        std::size_t stop = start;
        std::size_t last_break = start;
        int used = 0;
        for (; stop < characters.size(); ++stop) {
            const auto current = characters[stop].code;
            if (stop > start && word_boundary(characters[stop - 1].code, current)) last_break = stop;
            const int glyph_width = advance(current);
            if (stop > start && glyph_width > width - used) break;
            used += glyph_width;
        }
        const std::size_t next = stop < characters.size() && last_break > start ? last_break : stop;
        std::size_t end = next;
        if (next < characters.size()) {
            while (end > start + 1 && space(characters[end - 1].code)) --end;
        }
        const auto first_byte = characters[start].begin;
        lines.push_back(text.substr(first_byte, characters[end - 1].end - first_byte));
        start = next;
        while (start < characters.size() && space(characters[start].code)) ++start;
    }
    return lines;
}

}  // namespace nodzh
