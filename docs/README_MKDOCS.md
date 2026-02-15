# FMU Manipulation Toolbox Documentation

Professional documentation built with MkDocs Material.

## Quick Start

### Prerequisites

```bash
pip install mkdocs-material
pip install mkdocs-minify-plugin
```

### Build Documentation

```bash
# Development server with live reload
mkdocs serve

# Build static site
mkdocs build

# Deploy to GitHub Pages
mkdocs gh-deploy
```

## Structure

```
docs/
├── index.md                 # Homepage
├── getting-started.md       # Quick start guide  
├── installation.md          # Installation guide
├── user-guide/             # User guides
│   ├── gui-usage.md
│   ├── cli-usage.md
│   └── python-api.md
├── features/               # Feature documentation
├── examples/               # Examples and use cases
├── reference/              # API/CLI reference
├── help/                   # Help and support
│   ├── faq.md
│   └── troubleshooting.md
├── about/                  # About, license, credits
├── stylesheets/            # Custom CSS
├── javascripts/            # Custom JS
└── includes/               # Reusable content
```

## Features

- **Material Design**: Modern, responsive UI
- **Dark Mode**: Automatic dark/light theme switching
- **Search**: Full-text search with highlighting
- **Navigation**: Tabs, sections, and breadcrumbs
- **Code Blocks**: Syntax highlighting with copy button
- **Admonitions**: Notes, warnings, tips, examples
- **Tabs**: Tabbed content for multiple options
- **Cards**: Grid cards for feature showcases
- **Icons**: Material Design Icons integration

## Configuration

Edit `mkdocs.yml` to customize:

- Site metadata
- Theme colors and features
- Navigation structure
- Plugins and extensions
- Social links

## Deployment

### GitHub Pages

```bash
mkdocs gh-deploy
```

### Manual Deployment

```bash
mkdocs build
# Upload site/ directory to web server
```

## Writing Documentation

### Admonitions

```markdown
!!! note "Optional Title"
    Content here

!!! tip
    Helpful information

!!! warning
    Important warning

!!! danger
    Critical information
```

### Code Blocks with Tabs

```markdown
=== "Python"
    
    ```python
    code here
    ```

=== "Bash"
    
    ```bash
    code here
    ```
```

### Cards Grid

```markdown
<div class="grid cards" markdown>

-   :material-icon: __Title__
    
    ---
    
    Description

-   :material-icon: __Title__
    
    ---
    
    Description

</div>
```

## More Information

- [MkDocs Documentation](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
