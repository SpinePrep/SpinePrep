#!/usr/bin/env python3
"""Generate API reference documentation from workflow/lib modules."""

import argparse
import ast
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def parse_module(file_path: Path) -> Dict[str, Any]:
    """Parse Python module and extract function/class information."""
    try:
        with open(file_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return {}

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {}

    module_info = {
        "functions": [],
        "classes": [],
        "module_docstring": ast.get_docstring(tree),
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            if not node.name.startswith("_"):  # Skip private functions
                func_info = {
                    "name": node.name,
                    "docstring": ast.get_docstring(node),
                    "args": [arg.arg for arg in node.args.args],
                    "returns": (
                        getattr(node.returns, "id", None) if node.returns else None
                    ),
                }
                module_info["functions"].append(func_info)

        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):  # Skip private classes
                class_info = {
                    "name": node.name,
                    "docstring": ast.get_docstring(node),
                    "methods": [],
                }

                # Extract methods
                for method in node.body:
                    if isinstance(
                        method, ast.FunctionDef
                    ) and not method.name.startswith("_"):
                        method_info = {
                            "name": method.name,
                            "docstring": ast.get_docstring(method),
                            "args": [arg.arg for arg in method.args.args],
                            "returns": (
                                getattr(method.returns, "id", None)
                                if method.returns
                                else None
                            ),
                        }
                        class_info["methods"].append(method_info)

                # Sort methods deterministically by name
                class_info["methods"] = sorted(
                    class_info["methods"], key=lambda m: m["name"]
                )

                module_info["classes"].append(class_info)

    # Sort functions and classes deterministically by name
    module_info["functions"] = sorted(module_info["functions"], key=lambda f: f["name"])
    module_info["classes"] = sorted(module_info["classes"], key=lambda c: c["name"])
    return module_info


def format_function_signature(func_info: Dict[str, Any]) -> str:
    """Format function signature."""
    args = func_info["args"]
    returns = func_info["returns"]

    signature = f"{func_info['name']}({', '.join(args)})"
    if returns:
        signature += f" -> {returns}"

    return signature


def format_class_signature(class_info: Dict[str, Any]) -> str:
    """Format class signature."""
    return f"class {class_info['name']}"


def format_docstring(docstring: Optional[str], max_length: int = 100) -> str:
    """Format docstring for display."""
    if not docstring:
        return "No documentation available"

    # Get first line or truncate
    first_line = docstring.split("\n")[0].strip()
    if len(first_line) > max_length:
        first_line = first_line[: max_length - 3] + "..."

    return first_line


def generate_module_documentation(module_name: str, module_info: Dict[str, Any]) -> str:
    """Generate documentation for a single module."""
    lines = []

    # Module header
    lines.append(f"## {module_name}")
    lines.append("")

    if module_info["module_docstring"]:
        lines.append(module_info["module_docstring"])
        lines.append("")

    # Functions
    if module_info["functions"]:
        lines.append("### Functions")
        lines.append("")

        for func_info in module_info["functions"]:
            lines.append(f"#### `{format_function_signature(func_info)}`")
            lines.append("")
            lines.append(format_docstring(func_info["docstring"]))
            lines.append("")

    # Classes
    if module_info["classes"]:
        lines.append("### Classes")
        lines.append("")

        for class_info in module_info["classes"]:
            lines.append(f"#### `{format_class_signature(class_info)}`")
            lines.append("")
            lines.append(format_docstring(class_info["docstring"]))
            lines.append("")

            # Methods
            if class_info["methods"]:
                lines.append("**Methods:**")
                lines.append("")
                for method_info in class_info["methods"]:
                    lines.append(
                        f"- `{method_info['name']}({', '.join(method_info['args'])})`"
                    )
                    if method_info["docstring"]:
                        lines.append(
                            f"  - {format_docstring(method_info['docstring'], 80)}"
                        )
                lines.append("")

    return "\n".join(lines)


def generate_api_reference(lib_dir: Path) -> str:
    """Generate complete API reference documentation."""
    lines = []

    # Header
    lines.append("# API Reference")
    lines.append("")
    lines.append(
        "This page documents the SpinePrep API, including all functions and classes available in the `workflow/lib` modules."
    )
    lines.append("")

    # Find all Python modules
    python_files = list(lib_dir.glob("*.py"))
    python_files = [f for f in python_files if f.name != "__init__.py"]

    if not python_files:
        lines.append("No modules found in the specified directory.")
        return "\n".join(lines)

    # Process each module
    for py_file in sorted(python_files, key=lambda p: p.stem):
        module_name = py_file.stem
        module_info = parse_module(py_file)

        if module_info["functions"] or module_info["classes"]:
            module_doc = generate_module_documentation(module_name, module_info)
            lines.append(module_doc)
            lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append("The SpinePrep API provides the following modules:")
    lines.append("")

    for py_file in sorted(python_files, key=lambda p: p.stem):
        module_name = py_file.stem
        module_info = parse_module(py_file)

        func_count = len(module_info["functions"])
        class_count = len(module_info["classes"])

        lines.append(
            f"- **{module_name}**: {func_count} functions, {class_count} classes"
        )

    return "\n".join(lines)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Generate API reference documentation")
    parser.add_argument(
        "--lib-dir",
        type=Path,
        default="workflow/lib",
        help="Path to workflow/lib directory",
    )
    parser.add_argument(
        "--out", type=Path, default="docs/reference/api.md", help="Output file path"
    )
    parser.add_argument(
        "--check", action="store_true", help="Check if output file is up to date"
    )

    args = parser.parse_args()

    if not args.lib_dir.exists():
        print(f"Error: Library directory not found: {args.lib_dir}")
        sys.exit(1)

    # Generate documentation
    content = generate_api_reference(args.lib_dir)

    if args.check:
        # Check if output file exists and is up to date
        if args.out.exists():
            with open(args.out, "r") as f:
                existing_content = f.read()
            if existing_content.strip() == content.strip():
                print("API reference is up to date")
                return 0
            else:
                print("API reference is out of date")
                return 1
        else:
            print("API reference file does not exist")
            return 1
    else:
        # Write output file
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w") as f:
            f.write(content)
        print(f"API reference written to {args.out}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
