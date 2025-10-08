#!/usr/bin/env python3
"""Generate configuration reference documentation from schema."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def load_schema(schema_path: Path) -> Dict[str, Any]:
    """Load JSON schema from file."""
    try:
        with open(schema_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: Schema file not found: {schema_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in schema file: {e}")
        sys.exit(1)


def format_type(schema: Dict[str, Any]) -> str:
    """Format type information from schema."""
    if "type" in schema:
        if schema["type"] == "array":
            items_type = schema.get("items", {}).get("type", "any")
            return f"array of {items_type}"
        return schema["type"]
    elif "enum" in schema:
        return f"enum: {', '.join(map(str, schema['enum']))}"
    else:
        return "any"


def format_default(schema: Dict[str, Any]) -> str:
    """Format default value from schema."""
    if "default" in schema:
        default = schema["default"]
        if isinstance(default, str):
            return f'"{default}"'
        elif isinstance(default, bool):
            return str(default).lower()
        else:
            return str(default)
    return "None"


def format_example(schema: Dict[str, Any]) -> str:
    """Format example value from schema."""
    if "examples" in schema and schema["examples"]:
        example = schema["examples"][0]
        if isinstance(example, str):
            return f'"{example}"'
        elif isinstance(example, bool):
            return str(example).lower()
        else:
            return str(example)
    return "N/A"


def format_description(schema: Dict[str, Any]) -> str:
    """Format description from schema."""
    return schema.get("description", "No description available")


def generate_config_table(schema: Dict[str, Any], prefix: str = "") -> str:
    """Generate configuration table from schema."""
    if schema.get("type") != "object" or "properties" not in schema:
        return ""

    properties = schema["properties"]
    table_lines = []

    # Sort properties alphabetically
    for prop_name in sorted(properties.keys()):
        prop_schema = properties[prop_name]
        full_name = f"{prefix}.{prop_name}" if prefix else prop_name

        # Handle nested objects
        if prop_schema.get("type") == "object" and "properties" in prop_schema:
            table_lines.append(f"### {full_name}")
            table_lines.append("")
            table_lines.append(
                prop_schema.get("description", "No description available")
            )
            table_lines.append("")
            table_lines.append("| Parameter | Type | Default | Description |")
            table_lines.append("|-----------|------|---------|-------------|")

            # Add nested properties
            nested_table = generate_config_table(prop_schema, full_name)
            if nested_table:
                table_lines.append(nested_table)
            table_lines.append("")
            continue

        # Add property to table
        prop_type = format_type(prop_schema)
        prop_default = format_default(prop_schema)
        prop_description = format_description(prop_schema)

        table_lines.append(
            f"| `{full_name}` | {prop_type} | {prop_default} | {prop_description} |"
        )

    return "\n".join(table_lines)


def generate_config_reference(schema: Dict[str, Any]) -> str:
    """Generate complete configuration reference documentation."""
    lines = []

    # Header
    lines.append("# Configuration Reference")
    lines.append("")
    lines.append(
        "This page documents all configuration options available in SpinePrep."
    )
    lines.append("")

    # Schema information
    if "title" in schema:
        lines.append(f"**Schema**: {schema['title']}")
        lines.append("")

    if "description" in schema:
        lines.append(schema["description"])
        lines.append("")

    # Configuration table
    lines.append("## Configuration Options")
    lines.append("")
    lines.append("| Parameter | Type | Default | Description |")
    lines.append("|-----------|------|---------|-------------|")

    # Generate table content
    table_content = generate_config_table(schema)
    if table_content:
        lines.append(table_content)

    # Example configuration
    lines.append("")
    lines.append("## Example Configuration")
    lines.append("")
    lines.append("```yaml")
    lines.append("# Basic configuration")
    lines.append("bids_dir: /path/to/bids")
    lines.append("output_dir: /path/to/output")
    lines.append("n_procs: 4")
    lines.append("")
    lines.append("# Advanced configuration")
    lines.append("motion:")
    lines.append("  fd_threshold: 0.5")
    lines.append("  dvars_threshold: 75")
    lines.append("")
    lines.append("confounds:")
    lines.append("  acompcor: true")
    lines.append("  censor: true")
    lines.append("")
    lines.append("registration:")
    lines.append("  method: sct")
    lines.append("  template: PAM50")
    lines.append("```")

    return "\n".join(lines)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Generate configuration reference documentation"
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default="schemas/config.schema.json",
        help="Path to JSON schema file",
    )
    parser.add_argument(
        "--out", type=Path, default="docs/reference/config.md", help="Output file path"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check if output file is up to date"
    )

    args = parser.parse_args()

    # Load schema
    schema = load_schema(args.schema)

    # Generate documentation
    content = generate_config_reference(schema)

    if args.check:
        # Check if output file exists and is up to date
        if args.out.exists():
            with open(args.out, "r") as f:
                existing_content = f.read()
            if existing_content.strip() == content.strip():
                print("Configuration reference is up to date")
                return 0
            else:
                print("Configuration reference is out of date")
                return 1
        else:
            print("Configuration reference file does not exist")
            return 1
    else:
        # Write output file
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(content)
        print(f"Configuration reference written to {args.out}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
