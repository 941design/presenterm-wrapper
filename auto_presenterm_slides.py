#!/usr/bin/env python3
# auto_presenterm_slides.py

import sys
import re
import os
import shutil
import argparse
import yaml
import tempfile

# Built-in defaults — no config file needed for standard presentations
DEFAULTS = {
    "font_size": 28,
    "heading_ratio": 1.4,
    "image_scale": 1.0,
    "padding": [20, 80],
    "footer_ratio": 1.0,    # footer size relative to body (1.0 = same as body)
    "theme_override": None,
}

def load_wrapper_config(config_path=None):
    """Load wrapper configuration.

    Merges built-in defaults with optional presenterm-config.yaml from cwd.
    A config file is never required — the built-in defaults are sufficient.
    """
    result = dict(DEFAULTS)

    if config_path is None:
        candidates = [
            os.getenv("PRESENTERM_CONFIG"),
            os.path.join(os.getcwd(), "presenterm-config.yaml"),
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                config_path = candidate
                break

    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
            wrapper = config.get("wrapper", {})
            for key in result:
                if key in wrapper:
                    result[key] = wrapper[key]
        except Exception as e:
            print(f"Warning: failed to load config from {config_path}: {e}", file=sys.stderr)

    return result

def compute_font_sizes(target_pt, heading_ratio):
    """
    Compute optimal (base, body_mult, heading_mult) to match target_pt and heading_ratio.

    Algorithm: for each body_mult in 1..7, compute base = round(target_pt / body_mult),
    then heading_mult = clamp(round(body_mult * heading_ratio), 1, 7).
    Pick the combination with minimum total error.

    Returns: (base, body_mult, heading_mult)
    """
    best_error = float('inf')
    best = (9, 3, 2)

    for body_mult in range(1, 8):
        base = round(target_pt / body_mult)
        heading_mult = max(1, min(7, round(body_mult * heading_ratio)))

        body_error = abs(body_mult * base - target_pt)
        ratio_error = abs(heading_mult / body_mult - heading_ratio) * target_pt
        total_error = body_error + ratio_error

        if total_error < best_error:
            best_error = total_error
            best = (base, body_mult, heading_mult)

    return best

def parse_padding(padding_value):
    """
    Parse CSS-style padding shorthand into (top, right, bottom, left) in pixels.

    Accepts:
      - int/float: same padding all sides
      - [V, H]: vertical, horizontal
      - [T, R, B, L]: top, right, bottom, left
    """
    if padding_value is None:
        return (0, 0, 0, 0)

    if isinstance(padding_value, (int, float)):
        p = int(padding_value)
        return (p, p, p, p)

    if isinstance(padding_value, list):
        if len(padding_value) == 1:
            p = int(padding_value[0])
            return (p, p, p, p)
        elif len(padding_value) == 2:
            v, h = int(padding_value[0]), int(padding_value[1])
            return (v, h, v, h)
        elif len(padding_value) == 3:
            t, h, b = int(padding_value[0]), int(padding_value[1]), int(padding_value[2])
            return (t, h, b, h)
        elif len(padding_value) >= 4:
            return tuple(int(padding_value[i]) for i in range(4))

    return (0, 0, 0, 0)

def padding_to_presenterm_config(padding_px, base_font_size):
    """
    Convert pixel padding to presenterm max_columns/max_rows config.

    Uses terminal size to compute content area. Character cell dimensions
    are estimated from the base font size:
      - cell width ≈ base * 0.6
      - cell height ≈ base * 1.2

    Returns dict with defaults config keys, or empty dict if no padding.
    """
    top_px, right_px, bottom_px, left_px = padding_px

    if top_px == 0 and right_px == 0 and bottom_px == 0 and left_px == 0:
        return {}

    # Estimate character cell dimensions from base font size
    cell_width = base_font_size * 0.6
    cell_height = base_font_size * 1.2

    # Convert pixel padding to columns/rows
    left_cols = round(left_px / cell_width) if cell_width > 0 else 0
    right_cols = round(right_px / cell_width) if cell_width > 0 else 0
    top_rows = round(top_px / cell_height) if cell_height > 0 else 0
    bottom_rows = round(bottom_px / cell_height) if cell_height > 0 else 0

    # Query terminal dimensions
    try:
        term_cols, term_rows = shutil.get_terminal_size()
    except Exception:
        term_cols, term_rows = 200, 50  # fallback

    result = {}

    # Horizontal padding → max_columns + alignment
    h_total = left_cols + right_cols
    if h_total > 0 and term_cols > h_total:
        result["max_columns"] = term_cols - h_total
        if left_cols == right_cols:
            result["max_columns_alignment"] = "center"
        elif left_cols > right_cols:
            # More padding on left → shift content right
            result["max_columns_alignment"] = "right"
        else:
            result["max_columns_alignment"] = "left"

    # Vertical padding → max_rows + alignment
    v_total = top_rows + bottom_rows
    if v_total > 0 and term_rows > v_total:
        result["max_rows"] = term_rows - v_total
        if top_rows == bottom_rows:
            result["max_rows_alignment"] = "center"
        elif top_rows > bottom_rows:
            result["max_rows_alignment"] = "bottom"
        else:
            result["max_rows_alignment"] = "top"

    return result

def parse_frontmatter(lines):
    """
    Parse frontmatter and extract wrapper config keys.
    Returns (metadata_dict, frontmatter_end_idx, extracted_wrapper_config).

    Strips font_size and heading_ratio from metadata so presenterm doesn't see them.
    """
    if not lines or lines[0].strip() != "---":
        return {}, -1, {}

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, -1, {}

    # Use yaml.safe_load for proper nested YAML support
    fm_text = "".join(lines[1:end_idx])
    try:
        metadata = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        metadata = {}

    # Extract and remove all wrapper keys from metadata
    wrapper_config = {}
    wrapper_keys = {
        "font_size": int,
        "heading_ratio": float,
        "footer_ratio": float,
        "image_scale": float,
        "padding": None,  # kept as-is (int or list)
    }
    for key, convert in wrapper_keys.items():
        if key in metadata:
            try:
                val = metadata.pop(key)
                wrapper_config[key] = convert(val) if convert else val
            except (ValueError, TypeError):
                metadata.pop(key, None)

    return metadata, end_idx, wrapper_config

def write_frontmatter(lines, metadata, end_idx, theme_override=None,
                      heading_mult=None, body_mult=None, footer_mult=None):
    """Reconstruct frontmatter with given metadata, injecting theme override and font sizes."""

    def _ensure_theme_override(fm_dict):
        """Ensure fm_dict has theme.override dict structure."""
        if "theme" not in fm_dict:
            fm_dict["theme"] = {}
        if isinstance(fm_dict["theme"], str):
            fm_dict["theme"] = {"name": fm_dict["theme"]}
        if "override" not in fm_dict["theme"]:
            fm_dict["theme"]["override"] = {}

    def _inject_font_sizes(fm_dict, heading_mult, body_mult, footer_mult):
        """Inject font sizes for intro slide and footer."""
        _ensure_theme_override(fm_dict)
        override = fm_dict["theme"]["override"]

        # Intro slide: title=heading, subtitle/date/author=body
        if "intro_slide" not in override:
            override["intro_slide"] = {}
        intro = override["intro_slide"]

        if "title" not in intro:
            intro["title"] = {}
        if "font_size" not in intro["title"]:
            intro["title"]["font_size"] = heading_mult

        for key in ("subtitle", "event", "location", "date"):
            if key not in intro:
                intro[key] = {}
            if "font_size" not in intro[key]:
                intro[key]["font_size"] = body_mult

        if "author" not in intro:
            intro["author"] = {}
        if "font_size" not in intro["author"]:
            intro["author"]["font_size"] = body_mult

        # Footer font size — ensure footer has style (required by presenterm)
        if footer_mult and footer_mult > 0:
            if "footer" not in override:
                override["footer"] = {"style": "template"}
            footer = override["footer"]
            if isinstance(footer, dict):
                if "style" not in footer:
                    footer["style"] = "template"
                if "font_size" not in footer:
                    footer["font_size"] = footer_mult

    if end_idx < 0:
        if not theme_override and heading_mult is None:
            return lines
        fm_dict = {}
    else:
        # Build frontmatter dict from parsed metadata
        fm_dict = {}
        for key, value in metadata.items():
            fm_dict[key] = value

    # Inject theme override (merge with any existing theme from frontmatter)
    if theme_override:
        _ensure_theme_override(fm_dict)
        # Merge: frontmatter values take precedence over config
        for k, v in theme_override.items():
            if k not in fm_dict["theme"]["override"]:
                fm_dict["theme"]["override"][k] = v

    # Inject font sizes (intro slide + footer)
    if heading_mult is not None and body_mult is not None:
        _inject_font_sizes(fm_dict, heading_mult, body_mult, footer_mult)

    fm_yaml = yaml.dump(fm_dict, default_flow_style=False, sort_keys=False)
    result = ["---\n", fm_yaml, "---\n"]
    if end_idx < 0:
        return result + lines
    return result + lines[end_idx + 1:]

def add_slide_delimiters(input_path, output_path, level=1, font_size=None, heading_ratio=None,
                         theme_override=None, footer_ratio=1.0):
    """Insert <!-- end_slide --> before each heading of given level or higher"""
    slide_heading_pattern = re.compile(r'^\s*(#{1,' + str(level) + r'})\s+.+')
    any_heading_pattern = re.compile(r'^\s*(#{1,6})\s+.+')
    horizontal_rule_pattern = re.compile(r'^\s{0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})\s*$')
    code_fence_pattern = re.compile(r'^\s*```+')
    table_separator_pattern = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$')

    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Parse frontmatter
    metadata, frontmatter_end_idx, wrapper_config = parse_frontmatter(lines)

    # Use frontmatter overrides if provided
    if "font_size" in wrapper_config:
        font_size = wrapper_config["font_size"]
    if "heading_ratio" in wrapper_config:
        heading_ratio = wrapper_config["heading_ratio"]
    if "footer_ratio" in wrapper_config:
        footer_ratio = wrapper_config["footer_ratio"]

    # Compute font sizes
    base, body_mult, heading_mult = compute_font_sizes(font_size, heading_ratio)
    footer_mult = max(1, min(7, round(body_mult * footer_ratio)))

    # Reconstruct frontmatter without wrapper keys, injecting theme override
    result = write_frontmatter(lines, metadata, frontmatter_end_idx,
                              theme_override=theme_override,
                              heading_mult=heading_mult, body_mult=body_mult,
                              footer_mult=footer_mult)

    # Process the body
    in_slide = False
    first_slide_heading_seen = False
    in_code_block = False
    dedent_code_block = False
    dedent_prefix = ""
    body_start_idx = frontmatter_end_idx + 1 if frontmatter_end_idx >= 0 else 0

    # Skip the rewritten frontmatter
    body_lines = lines[body_start_idx:]
    processed = []

    i = 0
    while i < len(body_lines):
        line = body_lines[i]

        if horizontal_rule_pattern.match(line):
            i += 1
            continue

        # Normalize indented code fences
        fence_match = re.match(r'^([ \t]+)(```+.*)$', line)
        if not in_code_block and fence_match:
            dedent_prefix = fence_match.group(1)
            line = fence_match.group(2) + ('\n' if line.endswith('\n') else '')
            dedent_code_block = True
        elif in_code_block and dedent_code_block and dedent_prefix and line.startswith(dedent_prefix):
            line = line[len(dedent_prefix):]

        if not in_code_block and i + 1 < len(body_lines):
            next_line = body_lines[i + 1]
            if '|' in line and table_separator_pattern.match(next_line):
                processed.append('<!-- alignment: center -->\n')
                while i < len(body_lines) and '|' in body_lines[i] and body_lines[i].strip():
                    processed.append(body_lines[i])
                    i += 1
                processed.append('<!-- alignment: left -->\n')
                continue

        heading_match = any_heading_pattern.match(line)
        if heading_match:
            heading_level = len(heading_match.group(1))

            if slide_heading_pattern.match(line):
                if in_slide and first_slide_heading_seen:
                    processed.append('<!-- end_slide -->\n')
                first_slide_heading_seen = True

            # Inject font_size before headings (h1, h2)
            if heading_level == 1:
                processed.append(f'<!-- font_size: {heading_mult} -->\n')
            elif heading_level == 2:
                processed.append(f'<!-- font_size: {heading_mult} -->\n')

            processed.append(line)

            # Restore body font size after headings and add spacing
            if heading_level in (1, 2):
                processed.append(f'<!-- font_size: {body_mult} -->\n')
                processed.append('<!-- new_line -->\n')

            if slide_heading_pattern.match(line):
                in_slide = True
        else:
            processed.append(line)

        if code_fence_pattern.match(line):
            in_code_block = not in_code_block
            if not in_code_block:
                dedent_code_block = False
                dedent_prefix = ""
        i += 1

    # Prepend the rewritten frontmatter to the result
    with open(output_path, 'w', encoding='utf-8') as f:
        # Write the frontmatter we reconstructed
        f.writelines(result[:len(result) - len(body_lines)])
        # Write the processed body
        f.writelines(processed)

    print(f"Created {output_path} with automatic slide breaks (body_font={body_mult}, heading_font={heading_mult}, base={base})")
    return base, body_mult, heading_mult

PRESENTERM_DEFAULTS = {
    "defaults": {
        "terminal_font_size": 1,
    },
    "options": {
        "list_item_newlines": 1,
        "implicit_slide_ends": False,
        "incremental_lists": False,
        "strict_front_matter_parsing": True,
        "auto_render_languages": ["mermaid", "latex"],
    },
}

def create_clean_config(config_path=None, padding_config=None):
    """
    Generate a presenterm config file.

    If config_path is given, loads it and strips the wrapper section.
    Otherwise uses built-in defaults. Injects padding-derived settings.
    Returns path to temp config.
    """
    try:
        config = {}

        if config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                lines = f.readlines()

            # Remove wrapper section
            in_wrapper = False
            cleaned_lines = []
            for line in lines:
                if line.strip().startswith('wrapper:'):
                    in_wrapper = True
                    continue
                if in_wrapper and line and not line[0].isspace() and line.strip():
                    in_wrapper = False
                if in_wrapper:
                    continue
                cleaned_lines.append(line)

            config = yaml.safe_load("".join(cleaned_lines)) or {}

        # Merge built-in defaults for any missing keys
        for key, value in PRESENTERM_DEFAULTS.items():
            if key not in config:
                config[key] = value
            elif isinstance(value, dict):
                for k, v in value.items():
                    if k not in config[key]:
                        config[key][k] = v

        # Inject padding-derived settings
        if padding_config:
            if "defaults" not in config:
                config["defaults"] = {}
            for key in ("max_columns", "max_columns_alignment", "max_rows", "max_rows_alignment"):
                if key in padding_config:
                    config["defaults"][key] = padding_config[key]

        fd, temp_path = tempfile.mkstemp(suffix=".yaml", prefix="presenterm-run-")
        with os.fdopen(fd, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        return temp_path
    except Exception as e:
        print(f"Warning: failed to create config: {e}", file=sys.stderr)
        return None

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

    # Load wrapper config
    wrapper_config = load_wrapper_config()

    # Process slides (may extract font_size from frontmatter)
    base, body_mult, heading_mult = add_slide_delimiters(
        input_file,
        output_file,
        args.heading_level,
        font_size=wrapper_config["font_size"],
        heading_ratio=wrapper_config["heading_ratio"],
        theme_override=wrapper_config.get("theme_override"),
        footer_ratio=wrapper_config.get("footer_ratio", 1.0),
    )

    # Compute padding config from pixel values
    padding_px = parse_padding(wrapper_config.get("padding"))
    padding_config = padding_to_presenterm_config(padding_px, base)

    # Find presenterm-config.yaml in cwd (optional)
    config_file = os.path.join(os.getcwd(), "presenterm-config.yaml")
    if not os.path.exists(config_file):
        config_file = None

    # Generate clean presenterm config (wrapper section removed, padding injected)
    temp_config_path = create_clean_config(config_file, padding_config)

    # Build presenterm command
    presenterm_cmd = ["presenterm"]
    if temp_config_path:
        presenterm_cmd.extend(["--config-file", temp_config_path])
    presenterm_cmd.extend(presenterm_args)
    presenterm_cmd.append(output_file)

    # Start presentation immediately (replace current process)
    os.execvp("presenterm", presenterm_cmd)
