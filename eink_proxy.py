#!/usr/bin/env python3
"""
E-ink 7-Color Image Converter Proxy Server (Docker Version)
Converts images to 7-color e-ink palette with intelligent dithering detection
"""

from flask import Flask, send_file, request
from PIL import Image, ImageFilter, ImageEnhance
import requests
import io
import os

app = Flask(__name__)

# Define the 7 colors your e-ink display supports
EINK_PALETTE = [
    (0, 0, 0),       # Black
    (255, 255, 255), # White
    (255, 0, 0),     # Red
    (255, 255, 0),   # Yellow
    (0, 255, 0),     # Green
    (0, 0, 255),     # Blue
    (255, 165, 0),   # Orange
]

# Get configuration from environment variables
SOURCE_URL = os.environ.get('SOURCE_URL', 'http://192.168.1.199:10000/lovelace-main/einkpanelcolor?viewport=800x480')

def find_closest_color(pixel, palette):
    """Find the closest color in the palette."""
    min_distance = float('inf')
    closest_color = palette[0]
    
    for color in palette:
        distance = sum((p - c) ** 2 for p, c in zip(pixel, color))
        if distance < min_distance:
            min_distance = distance
            closest_color = color
    
    return closest_color

def should_use_dithering(img, threshold=0.20):
    """
    Analyze image to determine if dithering would improve quality.
    
    Args:
        img: PIL Image object
        threshold: Edge density threshold (0-1). Higher = more strict about NO dithering.
    
    Returns:
        True if dithering recommended, False otherwise
    """
    # Convert to grayscale for edge detection
    gray = img.convert('L')
    
    # Resize for faster analysis (sample the image)
    sample_size = (200, 120)
    gray_small = gray.resize(sample_size, Image.Resampling.LANCZOS)
    
    # Detect edges using filter
    edges = gray_small.filter(ImageFilter.FIND_EDGES)
    
    # Calculate edge density (how many pixels are edges)
    edge_pixels = sum(1 for pixel in edges.getdata() if pixel > 30)
    total_pixels = sample_size[0] * sample_size[1]
    edge_density = edge_pixels / total_pixels
    
    # Calculate color variance (photos have more varied colors)
    img_small = img.resize(sample_size, Image.Resampling.LANCZOS)
    colors = img_small.getcolors(maxcolors=10000)
    
    if colors:
        unique_colors = len(colors)
        color_diversity = unique_colors / total_pixels
    else:
        color_diversity = 1.0  # Many unique colors
    
    print(f"Image analysis: edge_density={edge_density:.3f}, color_diversity={color_diversity:.3f}")
    
    # Decision logic - conservative (favors NO dithering)
    use_dither = edge_density < threshold and color_diversity > 0.4
    
    print(f"Decision: {'DITHER (smooth photo)' if use_dither else 'NO DITHER (sharp UI)'}")
    
    return use_dither

def analyze_region(img, x, y, width, height):
    """
    Analyze a specific region to determine if it's photo-like.
    
    Returns:
        True if region should use dithering (photo-like)
        False if region should be sharp (UI-like)
    """
    # Extract the region
    region = img.crop((x, y, x + width, y + height))
    
    # Convert to grayscale for edge detection
    gray = region.convert('L')
    
    # Detect edges
    edges = gray.filter(ImageFilter.FIND_EDGES)
    
    # Calculate edge density
    edge_pixels = sum(1 for pixel in edges.getdata() if pixel > 30)
    total_pixels = width * height
    edge_density = edge_pixels / total_pixels if total_pixels > 0 else 0
    
    # Calculate color diversity
    colors = region.getcolors(maxcolors=10000)
    if colors:
        color_diversity = len(colors) / total_pixels
    else:
        color_diversity = 1.0
    
    # Photo-like if: low edges AND high color diversity
    is_photo = edge_density < 0.15 and color_diversity > 0.35
    
    return is_photo

def convert_image_regional(img, grid_size=50):
    """
    Convert image with REGIONAL dithering detection.
    Analyzes the image in a grid and applies dithering only to photo-like regions.
    
    Args:
        img: PIL Image object
        grid_size: Size of analysis grid (pixels). Smaller = more precise but slower.
    """
    img = img.convert('RGB')
    
    # Global enhancements
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.3)
    
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.4)
    
    width, height = img.size
    pixels = img.load()
    
    output_img = Image.new('RGB', (width, height))
    output_pixels = output_img.load()
    
    print(f"Converting {width}x{height} image with regional dithering (grid_size={grid_size})...")
    
    # Create a map of which regions should use dithering
    cols = (width + grid_size - 1) // grid_size
    rows = (height + grid_size - 1) // grid_size
    
    print(f"Analyzing {rows}x{cols} = {rows*cols} regions...")
    dither_map = {}
    
    for row in range(rows):
        for col in range(cols):
            x_start = col * grid_size
            y_start = row * grid_size
            x_end = min(x_start + grid_size, width)
            y_end = min(y_start + grid_size, height)
            
            region_width = x_end - x_start
            region_height = y_end - y_start
            
            should_dither = analyze_region(img, x_start, y_start, region_width, region_height)
            dither_map[(row, col)] = should_dither
    
    # Count photo vs UI regions
    photo_regions = sum(1 for v in dither_map.values() if v)
    ui_regions = len(dither_map) - photo_regions
    print(f"Detected: {photo_regions} photo regions, {ui_regions} UI regions")
    
    # Apply sharpening to the whole image first (helps UI regions)
    img = img.filter(ImageFilter.SHARPEN)
    enhancer = ImageEnhance.Sharpness(img)
    img = enhancer.enhance(1.5)
    pixels = img.load()
    
    # Process each pixel
    for y in range(height):
        if y % 100 == 0:
            print(f"Processing row {y}/{height}")
        
        row = y // grid_size
        
        for x in range(width):
            col = x // grid_size
            
            # Determine if this pixel's region should use dithering
            use_dithering = dither_map.get((row, col), False)
            
            old_pixel = pixels[x, y]
            new_pixel = find_closest_color(old_pixel, EINK_PALETTE)
            output_pixels[x, y] = new_pixel
            
            # Apply dithering only if in a photo region
            if use_dithering:
                quant_error = tuple(old - new for old, new in zip(old_pixel, new_pixel))
                
                # Distribute error (Floyd-Steinberg)
                if x + 1 < width:
                    pixels[x + 1, y] = tuple(
                        min(255, max(0, p + int(qe * 7/16)))
                        for p, qe in zip(pixels[x + 1, y], quant_error)
                    )
                if x - 1 >= 0 and y + 1 < height:
                    pixels[x - 1, y + 1] = tuple(
                        min(255, max(0, p + int(qe * 3/16)))
                        for p, qe in zip(pixels[x - 1, y + 1], quant_error)
                    )
                if y + 1 < height:
                    pixels[x, y + 1] = tuple(
                        min(255, max(0, p + int(qe * 5/16)))
                        for p, qe in zip(pixels[x, y + 1], quant_error)
                    )
                if x + 1 < width and y + 1 < height:
                    pixels[x + 1, y + 1] = tuple(
                        min(255, max(0, p + int(qe * 1/16)))
                        for p, qe in zip(pixels[x + 1, y + 1], quant_error)
                    )
    
    print("Regional conversion complete!")
    return output_img

def convert_image(img, use_dithering=False):
    """Convert image to 7-color e-ink palette.
    
    Args:
        img: PIL Image object
        use_dithering: If True, use Floyd-Steinberg dithering (good for photos).
                      If False, use simple nearest-color (good for dashboards/UI).
    """
    img = img.convert('RGB')
    
    # For dashboards: sharpen text and lines first
    if not use_dithering:
        # Sharpen to make text and lines crisper
        img = img.filter(ImageFilter.SHARPEN)
        img = img.filter(ImageFilter.SHARPEN)  # Apply twice for extra sharpness
    
    # Increase contrast and saturation for better color matching
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.3)
    
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.4)
    
    # Increase sharpness even more for text
    if not use_dithering:
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(2.0)
    
    pixels = img.load()
    width, height = img.size
    
    output_img = Image.new('RGB', (width, height))
    output_pixels = output_img.load()
    
    print(f"Converting {width}x{height} image to 7-color e-ink palette (dithering: {use_dithering})...")
    
    if use_dithering:
        # Floyd-Steinberg dithering (for photos)
        for y in range(height):
            if y % 50 == 0:
                print(f"Processing row {y}/{height}")
                
            for x in range(width):
                old_pixel = pixels[x, y]
                new_pixel = find_closest_color(old_pixel, EINK_PALETTE)
                output_pixels[x, y] = new_pixel
                
                quant_error = tuple(old - new for old, new in zip(old_pixel, new_pixel))
                
                # Distribute error to neighboring pixels
                if x + 1 < width:
                    pixels[x + 1, y] = tuple(
                        min(255, max(0, p + int(qe * 7/16)))
                        for p, qe in zip(pixels[x + 1, y], quant_error)
                    )
                if x - 1 >= 0 and y + 1 < height:
                    pixels[x - 1, y + 1] = tuple(
                        min(255, max(0, p + int(qe * 3/16)))
                        for p, qe in zip(pixels[x - 1, y + 1], quant_error)
                    )
                if y + 1 < height:
                    pixels[x, y + 1] = tuple(
                        min(255, max(0, p + int(qe * 5/16)))
                        for p, qe in zip(pixels[x, y + 1], quant_error)
                    )
                if x + 1 < width and y + 1 < height:
                    pixels[x + 1, y + 1] = tuple(
                        min(255, max(0, p + int(qe * 1/16)))
                        for p, qe in zip(pixels[x + 1, y + 1], quant_error)
                    )
    else:
        # Simple nearest-color matching (for dashboards/UI - NO dithering)
        for y in range(height):
            if y % 100 == 0:
                print(f"Processing row {y}/{height}")
                
            for x in range(width):
                old_pixel = pixels[x, y]
                new_pixel = find_closest_color(old_pixel, EINK_PALETTE)
                output_pixels[x, y] = new_pixel
    
    print("Conversion complete!")
    return output_img

@app.route('/eink-image')
def convert_proxy():
    """Main endpoint that converts images on-the-fly."""
    print(f"Received request for e-ink image conversion")
    print(f"Fetching from: {SOURCE_URL}")
    
    # Check dithering mode:
    # - 'false' (DEFAULT): No dithering - best for pure dashboards
    # - 'regional': Regional detection - dither only photo areas (BEST for mixed content)
    # - 'auto': Automatically detect whole image
    # - 'true': Force dithering everywhere
    dither_mode = request.args.get('dither', 'false').lower()
    
    try:
        # Fetch the original image
        response = requests.get(SOURCE_URL, timeout=15)
        response.raise_for_status()
        print(f"Successfully fetched image ({len(response.content)} bytes)")
        
        # Open image
        img = Image.open(io.BytesIO(response.content))
        print(f"Image size: {img.size}, mode: {img.mode}")
        
        # Determine conversion strategy
        if dither_mode == 'regional':
            # Regional dithering - best for dashboards with photos
            print("Using REGIONAL dithering detection")
            converted_img = convert_image_regional(img, grid_size=50)
        elif dither_mode == 'auto':
            # Auto-detect whole image
            use_dithering = should_use_dithering(img)
            print(f"Auto-detection: dithering={'ON' if use_dithering else 'OFF'}")
            converted_img = convert_image(img, use_dithering=use_dithering)
        elif dither_mode == 'true':
            # Force dithering
            print("Forced: dithering=ON")
            converted_img = convert_image(img, use_dithering=True)
        else:
            # No dithering (default)
            print("Forced: dithering=OFF")
            converted_img = convert_image(img, use_dithering=False)
        
        # Save to bytes buffer
        img_io = io.BytesIO()
        converted_img.save(img_io, 'PNG', optimize=True)
        img_io.seek(0)
        
        print(f"Returning converted image ({img_io.getbuffer().nbytes} bytes)")
        return send_file(img_io, mimetype='image/png')
    
    except Exception as e:
        error_msg = f"Error converting image: {str(e)}"
        print(error_msg)
        return error_msg, 500

@app.route('/health')
def health():
    """Health check endpoint."""
    return {'status': 'healthy', 'source_url': SOURCE_URL}, 200

@app.route('/')
def index():
    """Info page."""
    return f"""
    <html>
    <head>
        <title>E-ink 7-Color Image Proxy</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            h1 {{ color: #333; }}
            .info {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
            .endpoint {{ background: #e8f4f8; padding: 10px; margin: 10px 0; }}
            code {{ background: #333; color: #0f0; padding: 2px 5px; }}
        </style>
    </head>
    <body>
        <h1>E-ink 7-Color Image Proxy</h1>
        <div class="info">
            <p>This server converts images to 7-color e-ink palette with intelligent dithering detection.</p>
            <p><strong>Source URL:</strong> <code>{SOURCE_URL}</code></p>
            <p><strong>Supported colors:</strong> Black, White, Red, Yellow, Green, Blue, Orange</p>
        </div>
        
        <h2>Endpoints</h2>
        <div class="endpoint">
            <strong>GET /eink-image?dither=regional</strong> ⭐ RECOMMENDED for mixed dashboards<br>
            REGIONAL DITHERING: Analyzes image in grid, dithers only photo areas, keeps UI sharp<br>
            <a href="/eink-image?dither=regional">View regional mode</a>
        </div>
        <div class="endpoint">
            <strong>GET /eink-image</strong> (default)<br>
            NO DITHERING: Sharp everywhere, best for pure UI dashboards<br>
            <a href="/eink-image">View sharp mode</a>
        </div>
        <div class="endpoint">
            <strong>GET /eink-image?dither=auto</strong><br>
            AUTO-DETECT: Analyzes entire image and picks one mode<br>
            <a href="/eink-image?dither=auto">View auto mode</a>
        </div>
        <div class="endpoint">
            <strong>GET /eink-image?dither=true</strong><br>
            FORCE DITHERING: Dither everywhere, best for full-screen photos<br>
            <a href="/eink-image?dither=true">View full dither</a>
        </div>
        <div class="endpoint">
            <strong>GET /health</strong><br>
            Health check endpoint<br>
            <a href="/health">Check health</a>
        </div>
        
        <h2>Usage</h2>
        <p><strong>⭐ For dashboards WITH photos (RECOMMENDED):</strong></p>
        <code>url: http://YOUR_UNRAID_IP:5000/eink-image?dither=regional</code>
        <p>Divides image into 50x50px grid, analyzes each region separately:</p>
        <ul>
            <li>Photo-like regions (smooth gradients) → Dithering applied</li>
            <li>UI regions (sharp edges, text) → No dithering, kept sharp</li>
        </ul>
        
        <p><strong>For pure UI dashboards (no photos):</strong></p>
        <code>url: http://YOUR_UNRAID_IP:5000/eink-image</code>
        
        <p><strong>For full-screen photos:</strong></p>
        <code>url: http://YOUR_UNRAID_IP:5000/eink-image?dither=true</code>
    </body>
    </html>
    """

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("E-ink 7-Color Image Converter Proxy Server")
    print("=" * 60)
    print(f"Source URL: {SOURCE_URL}")
    print(f"Starting server on http://0.0.0.0:{port}")
    print(f"Access endpoint at: http://YOUR_IP:{port}/eink-image")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)