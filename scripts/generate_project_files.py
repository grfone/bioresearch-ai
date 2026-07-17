#!/usr/bin/env python3
"""
generate_project_files.py
A script to generate requirements.txt, pyproject.toml, and environment.yaml
for a Python project based on the current environment.
Usage:
    python generate_project_files.py
    # or with optional arguments:
    python generate_project_files.py --name myproject --version 0.1.0
"""
import argparse
import subprocess
import sys
from pathlib import Path

# Try to import tomli-w for TOML writing; fallback to manual string generation.
try:
    import tomli_w
    HAS_TOMLI_W = True
except ImportError:
    HAS_TOMLI_W = False

# Try to import yaml for YAML writing; fallback to manual string generation.
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def get_installed_packages():
    """Return a list of installed packages (name==version) from pip freeze."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze", "--local"],
            capture_output=True,
            text=True,
            check=True,
        )
        packages = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return packages
    except subprocess.CalledProcessError as e:
        print(f"Error running pip freeze: {e}", file=sys.stderr)
        sys.exit(1)


def parse_packages(packages):
    """Convert list of 'name==version' or local installs to dict of name: version."""
    dep_dict = {}
    for pkg in packages:
        if "==" in pkg:
            name, ver = pkg.split("==", 1)
            dep_dict[name] = ver
        elif "@" in pkg:
            # Handle local/editable installs like 'name @ file://...'
            name = pkg.split("@", 1)[0].strip()
            dep_dict[name] = None  # no version pin for local installs
        else:
            name = pkg.split()[0] if pkg else ""
            dep_dict[name] = None
    # Clean up names
    cleaned = {}
    for name, ver in dep_dict.items():
        if name:
            cleaned[name.strip()] = ver
    return cleaned


def get_project_metadata(args):
    """Gather project metadata from args or provided defaults."""
    name = args.name or "bioresearch-ai"
    version = args.version or "0.1.0"
    description = args.description or "An extensible AI platform for biomedical literature discovery, evidence synthesis, and scientific reasoning."
    return name, version, description


def generate_requirements_txt(packages):
    """Write requirements.txt with the package list."""
    with open("../requirements.txt", "w") as f:
        f.write("# Auto-generated requirements.txt\n")
        f.write("# Install with: pip install -r requirements.txt\n\n")
        for pkg in sorted(packages):
            f.write(pkg + "\n")
    print("✓ requirements.txt generated.")


def _remove_none_values(d):
    """Recursively remove keys with None values."""
    if isinstance(d, dict):
        return {k: _remove_none_values(v) for k, v in d.items() if v is not None}
    elif isinstance(d, list):
        return [_remove_none_values(item) for item in d]
    return d


def generate_pyproject_toml(name, version, description, dep_dict):
    """Generate pyproject.toml using tomli-w if available, else manual."""
    # Build dependencies list, handling None versions
    dependencies = []
    for pkg, ver in sorted(dep_dict.items()):
        if ver:
            dependencies.append(f"{pkg}=={ver}")
        else:
            dependencies.append(pkg)  # no version pin for local installs

    if HAS_TOMLI_W:
        project_data = {
            "project": {
                "name": name,
                "version": version,
                "description": description,
                "readme": "README.md" if Path("README.md").exists() else None,
                "requires-python": ">=3.8",
                "dependencies": dependencies,
                "license": {"text": "MIT"},
                "authors": [{"name": "Guillermo Ramajo Fernández"}],
            },
            "build-system": {
                "requires": ["setuptools>=61.0"],
                "build-backend": "setuptools.build_meta",
            },
        }
        # Clean None values before dumping
        clean_data = _remove_none_values(project_data)
        with open("../pyproject.toml", "wb") as f:
            tomli_w.dump(clean_data, f)
        print("✓ pyproject.toml generated (using tomli-w).")
    else:
        # Manual TOML generation
        lines = []
        lines.append("[project]")
        lines.append(f'name = "{name}"')
        lines.append(f'version = "{version}"')
        if description:
            lines.append(f'description = "{description}"')
        if Path("README.md").exists():
            lines.append('readme = "README.md"')
        lines.append('requires-python = ">=3.8"')
        lines.append("dependencies = [")
        for dep in dependencies:
            lines.append(f'    "{dep}",')
        lines.append("]")
        lines.append("[project.license]")
        lines.append('text = "MIT"')
        lines.append("[[project.authors]]")
        lines.append('name = "Guillermo Ramajo Fernández"')
        # Build system
        lines.append("[build-system]")
        lines.append('requires = ["setuptools>=61.0"]')
        lines.append('build-backend = "setuptools.build_meta"')

        with open("../pyproject.toml", "w") as f:
            f.write("# Auto-generated pyproject.toml\n\n")
            f.write("\n".join(lines))
        print("✓ pyproject.toml generated (manual fallback).")


def generate_environment_yaml(name, dep_dict):
    """Generate environment.yaml for conda."""
    deps = []
    for pkg, ver in sorted(dep_dict.items()):
        if ver:
            deps.append(f"{pkg}=={ver}")
        else:
            deps.append(pkg)
    deps.append("pip")

    if HAS_YAML:
        env_data = {
            "name": name,
            "channels": ["conda-forge", "defaults"],
            "dependencies": deps,
            "variables": {},
        }
        with open("../environment.yaml", "w") as f:
            yaml.dump(env_data, f, default_flow_style=False, sort_keys=False)
        print("✓ environment.yaml generated (using PyYAML).")
    else:
        # Manual YAML
        lines = [f"name: {name}"]
        lines.append("channels:")
        lines.append("  - conda-forge")
        lines.append("  - defaults")
        lines.append("dependencies:")
        for dep in deps:
            lines.append(f"  - {dep}")
        lines.append("variables: {}")
        with open("../environment.yaml", "w") as f:
            f.write("# Auto-generated environment.yaml\n")
            f.write("\n".join(lines))
        print("✓ environment.yaml generated (manual fallback).")


def main():
    parser = argparse.ArgumentParser(description="Generate project files.")
    parser.add_argument("--name", help="Project name")
    parser.add_argument("--version", help="Project version")
    parser.add_argument("--description", help="Project description")
    args = parser.parse_args()

    # 1. Get installed packages
    packages = get_installed_packages()
    if not packages:
        print("No packages found. Are you in a virtual environment?", file=sys.stderr)
        sys.exit(1)

    dep_dict = parse_packages(packages)

    # 2. Gather metadata
    name, version, description = get_project_metadata(args)

    # 3. Generate files
    generate_requirements_txt(packages)
    generate_pyproject_toml(name, version, description, dep_dict)
    generate_environment_yaml(name, dep_dict)

    print("\n✓ All files generated successfully!")
    print(" - requirements.txt")
    print(" - pyproject.toml")
    print(" - environment.yaml")


if __name__ == "__main__":
    main()