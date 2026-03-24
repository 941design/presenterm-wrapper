#!/usr/bin/env python3
# auto_presenterm_slides.py

import sys
import re
import os
import argparse

# Presenterm font sizes (presenterm supports integers 1-7 only).
# To adjust the base font size, modify KITTY_FONT_SIZE in the presenterm wrapper script.
# The multipliers here are applied relative to that base terminal font size.
BASE_FONT_SIZE = 3

HEADING_FONT_SIZE = 4
DEFAULT_BODY_FONT_SIZE = BASE_FONT_SIZE

def parse_frontmatter(lines):
    if not lines or lines[0].strip() != "---":
        return {}, -1

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, -1

    metadata = {}
    for raw in lines[1:end_idx]:
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip('"').strip("'")
        metadata[key] = value
    return metadata, end_idx

def add_slide_delimiters(input_path, output_path, level=1):
    """Insert <!-- end_slide --> before each heading of given level or higher"""
    slide_heading_pattern = re.compile(r'^\s*(#{1,' + str(level) + r'})\s+.+')
    any_heading_pattern = re.compile(r'^\s*(#{1,6})\s+.+')
    horizontal_rule_pattern = re.compile(r'^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})\s*$')
    code_fence_pattern = re.compile(r'^\s*```+')
    table_separator_pattern = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$')

    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    frontmatter_end_idx = -1
    if lines and lines[0].strip() == "---":
        _, frontmatter_end_idx = parse_frontmatter(lines)

    result = []
    if frontmatter_end_idx >= 0:
        result.extend(lines[:frontmatter_end_idx + 1])
    in_slide = False
    first_slide_heading_seen = False
    in_code_block = False
    dedent_code_block = False
    dedent_prefix = ""
    body_start_idx = frontmatter_end_idx + 1 if frontmatter_end_idx >= 0 else 0

    i = body_start_idx
    while i < len(lines):
        line = lines[i]

        if horizontal_rule_pattern.match(line):
            i += 1
            continue

        # Presenterm rejects fenced code blocks nested inside list structures.
        # Normalize by dedenting the whole fenced block to column 0.
        fence_match = re.match(r'^([ \t]+)(```+.*)$', line)
        if not in_code_block and fence_match:
            dedent_prefix = fence_match.group(1)
            line = fence_match.group(2) + ('\n' if line.endswith('\n') else '')
            dedent_code_block = True
        elif in_code_block and dedent_code_block and dedent_prefix and line.startswith(dedent_prefix):
            line = line[len(dedent_prefix):]

        if not in_code_block and i + 1 < len(lines):
            next_line = lines[i + 1]
            if '|' in line and table_separator_pattern.match(next_line):
                result.append('<!-- alignment: center -->\n')
                while i < len(lines) and '|' in lines[i] and lines[i].strip():
                    result.append(lines[i])
                    i += 1
                result.append('<!-- alignment: left -->\n')
                continue

        heading_match = any_heading_pattern.match(line)
        if heading_match:
            heading_level = len(heading_match.group(1))

            if slide_heading_pattern.match(line):
                if in_slide and first_slide_heading_seen:
                    result.append('<!-- end_slide -->\n')
                first_slide_heading_seen = True
            if heading_level == 1:
                result.append(f'<!-- font_size: {HEADING_FONT_SIZE} -->\n')
            elif heading_level == 2:
                result.append(f'<!-- font_size: {HEADING_FONT_SIZE} -->\n')
            result.append(line)
            if heading_level in (1, 2):
                result.append(f'<!-- font_size: {DEFAULT_BODY_FONT_SIZE} -->\n')
            if slide_heading_pattern.match(line):
                in_slide = True
        else:
            result.append(line)
        if code_fence_pattern.match(line):
            in_code_block = not in_code_block
            if not in_code_block:
                dedent_code_block = False
                dedent_prefix = ""
        i += 1

    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(result)

    print(f"Created {output_path} with automatic slide breaks")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preprocess markdown for presenterm and start presentation."
    )
    parser.add_argument("input_file", nargs="?")
    parser.add_argument(
        "--heading-level",
        type=int,
        default=2,
        help="Heading level threshold for slide splitting (default: 2).",
    )
    parser.add_argument(
        "--preprocessed-output",
        help="Optional path for preprocessed markdown output.",
    )
    args, presenterm_args = parser.parse_known_args()

    if not args.input_file:
        # No markdown input provided: pass through directly to presenterm.
        os.execvp("presenterm", ["presenterm", *presenterm_args])

    input_file = args.input_file
    if args.preprocessed_output:
        output_file = args.preprocessed_output
    else:
        input_basename = os.path.basename(input_file)
        output_file = os.path.join(
            os.getcwd(),
            f".presenterm-preprocessed-{input_basename}",
        )

    add_slide_delimiters(input_file, output_file, args.heading_level)

    # Start presentation immediately (replace current process)
    os.execvp("presenterm", ["presenterm", *presenterm_args, output_file])
