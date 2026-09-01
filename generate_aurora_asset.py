"""
Generates the high-fidelity 'Aurora Borealis' Aura Gradient background asset.
Based on the 6-layer multiply blend-mode nebula composition over a light (#faf8f2) backdrop
with analog film-grain texture overlay.
"""

import os
import math
import numpy as np
from PIL import Image, ImageFilter

def generate_aurora_image(width=2400, height=1500, output_path="assets/aurora_bg.png"):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Base color: #faf8f2 -> RGB (250, 248, 242)
    base_color = np.array([250.0, 248.0, 242.0], dtype=np.float32)
    current_img = np.ones((height, width, 3), dtype=np.float32) * base_color

    # Normalized coordinate grids
    y_coords, x_coords = np.mgrid[0:height, 0:width].astype(np.float32)
    x_norm = x_coords / float(width)
    y_norm = y_coords / float(height)

    def apply_multiply_layer(layer_rgb, layer_alpha, blur_radius, opacity=1.0):
        nonlocal current_img
        alpha = layer_alpha * opacity
        if blur_radius > 0:
            # Scale blur proportionally if high-res
            scale_factor = width / 1400.0
            actual_blur = max(1, int(blur_radius * scale_factor))
            rgba = np.dstack([layer_rgb, alpha * 255.0]).astype(np.uint8)
            pil_img = Image.fromarray(rgba, mode='RGBA')
            pil_img = pil_img.filter(ImageFilter.GaussianBlur(radius=actual_blur))
            blurred_arr = np.array(pil_img, dtype=np.float32)
            l_rgb = blurred_arr[:, :, :3]
            l_a = blurred_arr[:, :, 3] / 255.0
        else:
            l_rgb = layer_rgb
            l_a = alpha

        # CSS mix-blend-mode: multiply composite
        mult = (current_img * l_rgb) / 255.0
        current_img = current_img * (1.0 - l_a[:, :, None]) + mult * l_a[:, :, None]

    def make_linear_gradient(angle_deg, color_stops):
        css_rad = math.radians(angle_deg)
        dx = math.sin(css_rad)
        dy = -math.cos(css_rad)
        
        proj = (x_norm - 0.5) * dx + (y_norm - 0.5) * dy
        corners = [(-0.5)*dx + (-0.5)*dy, (0.5)*dx + (-0.5)*dy, (-0.5)*dx + (0.5)*dy, (0.5)*dx + (0.5)*dy]
        min_p = min(corners)
        max_p = max(corners)
        t = (proj - min_p) / (max_p - min_p + 1e-6)
        t = np.clip(t, 0.0, 1.0)

        r_out = np.zeros_like(t)
        g_out = np.zeros_like(t)
        b_out = np.zeros_like(t)
        a_out = np.zeros_like(t)

        sorted_stops = sorted(color_stops, key=lambda s: s[0])
        mask_first = t <= sorted_stops[0][0]
        r_out[mask_first] = sorted_stops[0][1][0]
        g_out[mask_first] = sorted_stops[0][1][1]
        b_out[mask_first] = sorted_stops[0][1][2]
        a_out[mask_first] = sorted_stops[0][1][3]

        for i in range(len(sorted_stops) - 1):
            p0, c0 = sorted_stops[i]
            p1, c1 = sorted_stops[i+1]
            mask = (t > p0) & (t <= p1)
            if np.any(mask):
                factor = (t[mask] - p0) / (p1 - p0 + 1e-6)
                r_out[mask] = c0[0] + (c1[0] - c0[0]) * factor
                g_out[mask] = c0[1] + (c1[1] - c0[1]) * factor
                b_out[mask] = c0[2] + (c1[2] - c0[2]) * factor
                a_out[mask] = c0[3] + (c1[3] - c0[3]) * factor

        mask_last = t > sorted_stops[-1][0]
        r_out[mask_last] = sorted_stops[-1][1][0]
        g_out[mask_last] = sorted_stops[-1][1][1]
        b_out[mask_last] = sorted_stops[-1][1][2]
        a_out[mask_last] = sorted_stops[-1][1][3]

        return np.dstack([r_out, g_out, b_out]), a_out

    def make_radial_gradient(cx, cy, rx, ry, color_stops):
        dist = np.sqrt(((x_norm - cx) / rx) ** 2 + ((y_norm - cy) / ry) ** 2)
        dist = np.clip(dist, 0.0, 1.0)

        r_out = np.zeros_like(dist)
        g_out = np.zeros_like(dist)
        b_out = np.zeros_like(dist)
        a_out = np.zeros_like(dist)

        sorted_stops = sorted(color_stops, key=lambda s: s[0])
        mask_first = dist <= sorted_stops[0][0]
        r_out[mask_first] = sorted_stops[0][1][0]
        g_out[mask_first] = sorted_stops[0][1][1]
        b_out[mask_first] = sorted_stops[0][1][2]
        a_out[mask_first] = sorted_stops[0][1][3]

        for i in range(len(sorted_stops) - 1):
            p0, c0 = sorted_stops[i]
            p1, c1 = sorted_stops[i+1]
            mask = (dist > p0) & (dist <= p1)
            if np.any(mask):
                factor = (dist[mask] - p0) / (p1 - p0 + 1e-6)
                r_out[mask] = c0[0] + (c1[0] - c0[0]) * factor
                g_out[mask] = c0[1] + (c1[1] - c0[1]) * factor
                b_out[mask] = c0[2] + (c1[2] - c0[2]) * factor
                a_out[mask] = c0[3] + (c1[3] - c0[3]) * factor

        mask_last = dist > sorted_stops[-1][0]
        r_out[mask_last] = sorted_stops[-1][1][0]
        g_out[mask_last] = sorted_stops[-1][1][1]
        b_out[mask_last] = sorted_stops[-1][1][2]
        a_out[mask_last] = sorted_stops[-1][1][3]

        return np.dstack([r_out, g_out, b_out]), a_out

    # Layer 1 - linear 154deg, blur 29px
    l1_stops = [
        (0.18, (12, 72, 61, 0.0)),
        (0.29, (12, 72, 61, 0.06)),
        (0.36, (0, 229, 255, 0.40)),
        (0.42, (255, 255, 255, 1.0)),
        (0.48, (73, 207, 158, 0.32)),
        (0.55, (38, 158, 119, 0.22)),
        (0.62, (0, 183, 255, 0.30)),
        (0.68, (15, 76, 65, 0.08)),
        (0.82, (15, 76, 65, 0.0)),
    ]
    rgb1, a1 = make_linear_gradient(154, l1_stops)
    apply_multiply_layer(rgb1, a1, blur_radius=29, opacity=1.0)

    # Layer 2 - linear 128deg, blur 22px, opacity 0.9
    l2_stops = [
        (0.28, (15, 82, 96, 0.0)),
        (0.38, (15, 82, 96, 0.06)),
        (0.43, (0, 183, 255, 0.35)),
        (0.48, (255, 255, 255, 1.0)),
        (0.52, (68, 197, 185, 0.22)),
        (0.57, (0, 229, 255, 0.25)),
        (0.62, (25, 105, 112, 0.10)),
        (0.76, (25, 105, 112, 0.0)),
    ]
    rgb2, a2 = make_linear_gradient(128, l2_stops)
    apply_multiply_layer(rgb2, a2, blur_radius=22, opacity=0.9)

    # Layer 3 - radial 78% 20% at 51% 53%, blur 101px, opacity 0.9
    l3_stops = [
        (0.0, (65, 183, 155, 0.24)),
        (0.45, (30, 102, 91, 0.10)),
        (0.82, (30, 102, 91, 0.0)),
    ]
    rgb3, a3 = make_radial_gradient(0.51, 0.53, 0.78, 0.20, l3_stops)
    apply_multiply_layer(rgb3, a3, blur_radius=101, opacity=0.9)

    # Layer 4 - radial 48% 9% at 52% 50%, blur 252px
    l4_stops = [
        (0.0, (190, 255, 226, 0.14)),
        (0.45, (91, 195, 163, 0.06)),
        (0.80, (91, 195, 163, 0.0)),
    ]
    rgb4, a4 = make_radial_gradient(0.52, 0.50, 0.48, 0.09, l4_stops)
    apply_multiply_layer(rgb4, a4, blur_radius=150, opacity=1.0)

    # Layer 5 - linear to top, blur 115px, opacity 0.9
    l5_stops = [
        (0.0, (1, 5, 13, 0.90)),
        (0.28, (2, 7, 16, 0.58)),
        (0.55, (3, 9, 20, 0.20)),
        (0.78, (3, 9, 20, 0.0)),
    ]
    rgb5, a5 = make_linear_gradient(0, l5_stops)
    apply_multiply_layer(rgb5, a5, blur_radius=115, opacity=0.9)

    # Layer 6 - radial 50% 28% at 72% 18%, blur 198px, opacity 0.7
    l6_stops = [
        (0.0, (89, 62, 151, 0.10)),
        (0.45, (57, 44, 100, 0.04)),
        (0.82, (57, 44, 100, 0.0)),
    ]
    rgb6, a6 = make_radial_gradient(0.72, 0.18, 0.50, 0.28, l6_stops)
    apply_multiply_layer(rgb6, a6, blur_radius=140, opacity=0.7)

    # Film-grain overlay (mix-blend-mode: overlay)
    rng = np.random.default_rng(42)
    noise = rng.normal(128.0, 16.0, (height, width)).astype(np.float32)
    noise = np.clip(noise, 0.0, 255.0)
    noise_3d = np.dstack([noise, noise, noise])

    norm_base = current_img / 255.0
    norm_noise = noise_3d / 255.0
    overlay = np.where(
        norm_base < 0.5,
        2.0 * norm_base * norm_noise,
        1.0 - 2.0 * (1.0 - norm_base) * (1.0 - norm_noise)
    ) * 255.0
    
    grain_opacity = 0.20
    final_img = current_img * (1.0 - grain_opacity) + overlay * grain_opacity
    final_img = np.clip(final_img, 0, 255).astype(np.uint8)

    img = Image.fromarray(final_img, mode='RGB')
    img.save(output_path, quality=95)
    print(f"[OK] Aurora Borealis asset generated: {output_path} ({width}x{height})")
    return img

if __name__ == "__main__":
    generate_aurora_image()
