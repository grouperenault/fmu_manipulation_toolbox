#!/usr/bin/env python3
"""
Generate a LinkedIn carousel PDF for FMU Manipulation Toolbox GUI presentation.
Each slide is 1080 × 1350 px (portrait 4:5 ratio).
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap

# Configuration
SLIDE_WIDTH = 1080
SLIDE_HEIGHT = 1350
BACKGROUND_COLOR = (43, 43, 43)  # #2b2b2b
ACCENT_COLOR = (69, 113, 164)    # #4571a4
TEXT_COLOR = (221, 221, 221)     # #dddddd
TITLE_COLOR = (255, 255, 255)    # white

PROJECT_ROOT = Path(__file__).parent
DOCS_ROOT = PROJECT_ROOT / "docs"
OUTPUT_PDF = PROJECT_ROOT / "fmu_manipulation_toolbox_linkedin_carousel.pdf"

# Try to load fonts, fallback to default if not available
try:
    FONT_TITLE = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48)
    FONT_BODY = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 24)
    FONT_SMALL = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 18)
except Exception:
    print("Warning: System fonts not found, using default font")
    FONT_TITLE = ImageFont.load_default()
    FONT_BODY = ImageFont.load_default()
    FONT_SMALL = ImageFont.load_default()

def create_blank_slide():
    """Create a blank slide with background color."""
    return Image.new('RGB', (SLIDE_WIDTH, SLIDE_HEIGHT), BACKGROUND_COLOR)

def add_text_to_slide(image, text, y_start=150, font=None, color=TEXT_COLOR, align='left', wrap_width=35):
    """Add wrapped text to slide."""
    if font is None:
        font = FONT_BODY
    
    draw = ImageDraw.Draw(image)
    x_start = 60
    x_width = SLIDE_WIDTH - 120
    
    # Wrap text
    wrapped_lines = []
    for line in text.split('\n'):
        if line.strip():
            wrapped_lines.extend(textwrap.wrap(line, width=wrap_width))
        else:
            wrapped_lines.append('')
    
    y = y_start
    for line in wrapped_lines:
        draw.text((x_start, y), line, fill=color, font=font)
        y += 50
    
    return y

def add_centered_text(image, text, y, font=None, color=TITLE_COLOR):
    """Add centered text to slide."""
    if font is None:
        font = FONT_TITLE
    
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (SLIDE_WIDTH - text_width) // 2
    draw.text((x, y), text, fill=color, font=font)
    return y + 80

def add_image_to_slide(image, img_path, y_start, max_height=800):
    """Add and resize image to slide."""
    if not Path(img_path).exists():
        print(f"Warning: Image not found: {img_path}")
        return y_start + max_height
    
    try:
        img = Image.open(img_path)
        # Resize to fit
        ratio = img.width / img.height
        new_height = min(max_height, img.height)
        new_width = int(new_height * ratio)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Center horizontally
        x_offset = (SLIDE_WIDTH - new_width) // 2
        image.paste(img, (x_offset, y_start))
        return y_start + new_height
    except Exception as e:
        print(f"Error loading image {img_path}: {e}")
        return y_start + max_height

def add_footer(image, text):
    """Add footer text at the bottom."""
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=FONT_SMALL)
    text_width = bbox[2] - bbox[0]
    x = (SLIDE_WIDTH - text_width) // 2
    y = SLIDE_HEIGHT - 60
    draw.text((x, y), text, fill=TEXT_COLOR, font=FONT_SMALL)

def create_slide_1():
    """Slide 1: Cover"""
    img = create_blank_slide()
    draw = ImageDraw.Draw(img)
    
    # Add accent bar at top
    draw.rectangle([(0, 0), (SLIDE_WIDTH, 8)], fill=ACCENT_COLOR)
    
    # Logo
    logo_path = DOCS_ROOT / "fmu_manipulation_toolbox.png"
    if logo_path.exists():
        add_image_to_slide(img, str(logo_path), 100, max_height=400)
    
    # Title
    add_centered_text(img, "FMU Manipulation Toolbox", 600, FONT_TITLE, TITLE_COLOR)
    
    # Subtitle
    subtitle = "3 graphical interfaces to analyze,\nmodify & combine FMUs"
    y = 750
    for line in subtitle.split('\n'):
        add_centered_text(img, line, y, FONT_BODY, ACCENT_COLOR)
        y += 80
    
    # Footer
    add_footer(img, "pip install fmu-manipulation-toolbox · Open Source · FMI 2.0 & 3.0")
    
    return img

def create_slide_2():
    """Slide 2: FMU Tool"""
    img = create_blank_slide()
    draw = ImageDraw.Draw(img)
    
    # Accent bar
    draw.rectangle([(0, 0), (SLIDE_WIDTH, 8)], fill=ACCENT_COLOR)
    
    # Title
    add_centered_text(img, "🔍 FMU Tool", 30, FONT_TITLE, TITLE_COLOR)
    add_centered_text(img, "Analyze & Modify", 100, FONT_BODY, ACCENT_COLOR)
    
    # Bullet points
    bullets = [
        "• Load any FMU and inspect ports",
        "• Rename variables, strip hierarchy",
        "• Remove ports by regex or type",
        "• Add 32↔64-bit remoting interfaces",
        "• Check FMI compliance (XSD)",
        "• Export port list to CSV"
    ]
    
    y = 250
    for bullet in bullets:
        add_text_to_slide(img, bullet, y, FONT_BODY, TEXT_COLOR)
        y += 65
    
    # Command
    draw.rectangle([(40, 700), (1040, 760)], outline=ACCENT_COLOR, width=2)
    add_centered_text(img, "fmutool-gui", 710, FONT_BODY, ACCENT_COLOR)
    
    # Image
    img_path = DOCS_ROOT / "user-guide" / "fmutool" / "fmutool-gui.png"
    add_image_to_slide(img, str(img_path), 800, max_height=450)
    
    add_footer(img, "docs/user-guide/fmutool/gui-usage.md")
    
    return img

def create_slide_3():
    """Slide 3: Variable Editor"""
    img = create_blank_slide()
    draw = ImageDraw.Draw(img)
    
    # Accent bar
    draw.rectangle([(0, 0), (SLIDE_WIDTH, 8)], fill=ACCENT_COLOR)
    
    # Title
    add_centered_text(img, "✏️ Variable Editor", 30, FONT_TITLE, TITLE_COLOR)
    add_centered_text(img, "Edit names & descriptions", 100, FONT_BODY, ACCENT_COLOR)
    
    # Bullet points
    bullets = [
        "• Drag & drop to load an FMU",
        "• Editable table for variables",
        "• Edit descriptions in real-time",
        "• Modify start/stop time settings",
        "• Filter & sort across columns",
        "• Save as new FMU (original safe)"
    ]
    
    y = 250
    for bullet in bullets:
        add_text_to_slide(img, bullet, y, FONT_BODY, TEXT_COLOR)
        y += 65
    
    # Command
    draw.rectangle([(40, 700), (1040, 760)], outline=ACCENT_COLOR, width=2)
    add_centered_text(img, "fmueditor", 710, FONT_BODY, ACCENT_COLOR)
    
    # Image
    img_path = DOCS_ROOT / "user-guide" / "fmutool" / "fmueditor.png"
    add_image_to_slide(img, str(img_path), 800, max_height=450)
    
    add_footer(img, "docs/user-guide/fmutool/fmueditor.md")
    
    return img

def create_slide_4():
    """Slide 4: Container Builder"""
    img = create_blank_slide()
    draw = ImageDraw.Draw(img)
    
    # Accent bar
    draw.rectangle([(0, 0), (SLIDE_WIDTH, 8)], fill=ACCENT_COLOR)
    
    # Title
    add_centered_text(img, "🔗 Container Builder", 30, FONT_TITLE, TITLE_COLOR)
    add_centered_text(img, "Visual FMU assembly", 100, FONT_BODY, ACCENT_COLOR)
    
    # Bullet points
    bullets = [
        "• Drag & drop FMUs onto canvas",
        "• Draw wires to connect ports",
        "• Auto-connect by matching names",
        "• Configure mappings & start values",
        "• Nested sub-containers with tree",
        "• Export as FMU or JSON"
    ]
    
    y = 250
    for bullet in bullets:
        add_text_to_slide(img, bullet, y, FONT_BODY, TEXT_COLOR)
        y += 65
    
    # Command
    draw.rectangle([(40, 700), (1040, 760)], outline=ACCENT_COLOR, width=2)
    add_centered_text(img, "fmucontainer-gui", 710, FONT_BODY, ACCENT_COLOR)
    
    # Image
    img_path = DOCS_ROOT / "user-guide" / "fmucontainer" / "fmucontainer-gui.png"
    add_image_to_slide(img, str(img_path), 800, max_height=450)
    
    add_footer(img, "docs/user-guide/fmucontainer/gui-usage.md")
    
    return img

def main():
    """Generate the carousel PDF."""
    print("Generating LinkedIn carousel PDF...")
    
    # Create slides
    slides = [
        create_slide_1(),
        create_slide_2(),
        create_slide_3(),
        create_slide_4(),
    ]
    
    # Save as PDF
    slides[0].save(
        OUTPUT_PDF,
        save_all=True,
        append_images=slides[1:],
        duration=200,
        loop=0,
        format='PDF'
    )
    
    print(f"✅ Carousel PDF generated: {OUTPUT_PDF}")
    print(f"📐 Dimensions: {SLIDE_WIDTH} × {SLIDE_HEIGHT} px (4:5 ratio)")
    print(f"📊 Number of slides: {len(slides)}")
    print(f"\n💡 Ready to upload to LinkedIn!")

if __name__ == "__main__":
    main()

