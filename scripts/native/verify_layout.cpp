#include "nod_layout.hpp"

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

using nodzh::Character;

namespace {
void require(bool valid, const char* message) {
    if (!valid) throw std::runtime_error(message);
}

std::vector<std::uint32_t> without_spaces(const std::vector<Character>& chars) {
    std::vector<std::uint32_t> result;
    for (const auto& ch : chars) {
        if (!nodzh::space(ch.code)) result.push_back(ch.code);
    }
    return result;
}

int width_of(std::uint32_t code) {
    if (code > 127) return 10;
    return nodzh::space(code) ? 4 : 7;
}

void check(std::string_view input, int width) {
    std::vector<Character> chars, line_chars;
    require(nodzh::decode(input, chars), "Source has invalid UTF-8");
    std::vector<std::uint32_t> all;
    for (const auto line : nodzh::wrap(input, chars, width, width_of)) {
        require(nodzh::decode(line, line_chars), "Line splits a UTF-8 sequence");
        int measured = 0;
        for (const auto& ch : line_chars) measured += width_of(ch.code);
        require(measured <= width || line_chars.size() == 1, "Line exceeds width");
        const auto visible = without_spaces(line_chars);
        all.insert(all.end(), visible.begin(), visible.end());
    }
    require(all == without_spaces(chars), "Wrapping changed visible characters or their order");
}
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    try {
        std::ifstream input(argv[1], std::ios::binary);
        require(static_cast<bool>(input), "Could not open translation corpus");
        std::vector<Character> chars;
        require(!nodzh::decode("\xc0\x80", chars), "Overlong sequence accepted");
        require(!nodzh::decode("\xed\xa0\x80", chars), "Surrogate accepted");
        require(!nodzh::decode("\xe8\xbe", chars), "Truncated sequence accepted");
        constexpr std::string_view sample = u8"输入 CD-Key  ";
        require(nodzh::decode(sample, chars), "Mixed title failed decoding");
        require(nodzh::wrap(sample, chars, 256, width_of).front() == sample, "Trailing padding lost");
        std::size_t rows = 0;
        std::string entry;
        while (std::getline(input, entry)) {
            ++rows;
            for (int width : {8, 10, 40, 75, 120, 320}) check(entry, width);
        }
        require(rows != 0 && input.eof(), "Corpus read failed");
        std::cout << rows << " records verified at six widths\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
