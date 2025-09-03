import os
import sys
import argparse
from typing import Tuple, Optional, List

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Text shaping for Arabic
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC = True
except Exception:
    HAS_ARABIC = False

from moviepy.editor import (
    ColorClip,
    ImageClip,
    CompositeVideoClip,
    AudioFileClip,
    VideoClip,
    vfx,
)


def hex_to_rgb(hx: str) -> Tuple[int, int, int]:
    hx = hx.lstrip('#')
    if len(hx) == 3:
        hx = ''.join([c * 2 for c in hx])
    return tuple(int(hx[i:i+2], 16) for i in (0, 2, 4))


def find_font(candidates: List[str]) -> Optional[str]:
    """Try to find a usable font file from common locations on Windows.
    Returns the first existing path or None.
    """
    search_dirs = [
        r"C:\\Windows\\Fonts",
        r"C:\\Windows\\fonts",
        os.getcwd(),  # current project folder (in case user drops a TTF here)
    ]
    for d in search_dirs:
        for name in candidates:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


def find_image(candidates: List[str]) -> Optional[str]:
    """Find an image by trying common locations and candidate names."""
    search_dirs = [
        os.getcwd(),
        os.path.join(os.getcwd(), "assets"),
    ]
    for d in search_dirs:
        for name in candidates:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return None


def shape_text_if_arabic(text: str) -> str:
    if not HAS_ARABIC:
        return text
    # Heuristic: if contains Arabic range, reshape and apply bidi
    if any('\u0600' <= ch <= '\u06FF' or '\u0750' <= ch <= '\u077F' for ch in text):
        reshaped_text = arabic_reshaper.reshape(text)
        return get_display(reshaped_text)
    return text


def render_text_image(
    text: str,
    font_path: str,
    font_size: int,
    color: Tuple[int, int, int],
    stroke_width: int = 0,
    stroke_fill: Tuple[int, int, int] = (0, 0, 0),
    padding: int = 10,
) -> Image.Image:
    """Render text to a transparent RGBA image tightly fit around the text."""
    txt = shape_text_if_arabic(text)
    font = ImageFont.truetype(font_path, font_size)

    # Measure text bbox
    temp_img = Image.new('RGBA', (4, 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(temp_img)
    bbox = draw.textbbox((0, 0), txt, font=font, stroke_width=stroke_width)
    w = (bbox[2] - bbox[0]) + 2 * padding
    h = (bbox[3] - bbox[1]) + 2 * padding

    img = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((padding, padding), txt, font=font, fill=color + (255,), stroke_width=stroke_width, stroke_fill=stroke_fill + (255,))
    return img


def image_to_clip(img: Image.Image, duration: float, fps: int) -> ImageClip:
    arr = np.array(img)
    clip = ImageClip(arr, ismask=False).set_duration(duration)
    clip.fps = fps
    return clip


def glow_for_image(img: Image.Image, radius: int = 12, strength: float = 0.6, scale: float = 1.02) -> Image.Image:
    """Create a soft glow from an RGBA text image by blurring and reducing alpha."""
    blur = img.filter(ImageFilter.GaussianBlur(radius))
    r, g, b, a = blur.split()
    a = a.point(lambda v: int(v * strength))
    glow = Image.merge('RGBA', (r, g, b, a))
    if scale != 1.0:
        new_w = max(1, int(glow.width * scale))
        new_h = max(1, int(glow.height * scale))
        glow = glow.resize((new_w, new_h), Image.LANCZOS)
    return glow


def make_radial_glow_overlay(width: int, height: int, color: Tuple[int, int, int], strength: float = 0.6, power: float = 2.0) -> Image.Image:
    """Create a colored radial glow RGBA image (center bright -> edges fade)."""
    yy, xx = np.mgrid[0:height, 0:width]
    cx, cy = width / 2.0, height / 2.0
    rx, ry = width / 2.0, height / 2.0
    r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    mask = np.clip(1.0 - np.power(np.clip(r, 0.0, 1.0), power), 0.0, 1.0)
    alpha = (mask * strength * 255.0).astype(np.uint8)
    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[..., 0] = color[0]
    overlay[..., 1] = color[1]
    overlay[..., 2] = color[2]
    overlay[..., 3] = alpha
    return Image.fromarray(overlay, mode='RGBA')


def create_vignette_clip(w: int, h: int, duration: float, strength: float = 0.35, power: float = 2.0, fps: int = 30) -> ImageClip:
    """Create a black vignette overlay as an ImageClip with alpha gradient."""
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = w / 2.0, h / 2.0
    rx, ry = w / 2.0, h / 2.0
    # normalized radial distance from center, 0 at center -> 1 at edges
    r = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    mask = np.clip(r ** power, 0.0, 1.0)
    alpha = (mask * strength * 255.0).astype(np.uint8)
    overlay = np.zeros((h, w, 4), dtype=np.uint8)
    overlay[..., 0:3] = 0  # black
    overlay[..., 3] = alpha
    return ImageClip(overlay, ismask=False).set_duration(duration).set_fps(fps)


def make_noise_clip(w: int, h: int, duration: float, fps: int = 30, opacity: float = 0.04) -> VideoClip:
    """Create a subtle animated grain/noise overlay clip (downsampled for speed)."""
    dw, dh = max(2, w // 2), max(2, h // 2)

    def _frame(t):
        arr = (np.random.rand(dh, dw, 3) * 255).astype(np.uint8)
        # upscale to target size
        arr = np.repeat(np.repeat(arr, h // dh + 1, axis=0), w // dw + 1, axis=1)[:h, :w]
        return arr

    noise = VideoClip(make_frame=_frame, duration=duration).set_fps(fps)
    return noise.set_opacity(opacity)

def build_intro(
    out_path: str,
    music_path: Optional[str] = None,
    w: int = 1920,
    h: int = 1080,
    fps: int = 30,
    font_ar: Optional[str] = None,
    font_en: Optional[str] = None,
):
    duration_total = 16.0

    # Colors
    GOLD = hex_to_rgb('#D4AF37')
    SILVER = hex_to_rgb('#C0C0C0')
    LIGHT_BLUE = hex_to_rgb('#66B2FF')
    MET_BLUE = hex_to_rgb('#1E3A8A')
    WHITE = (255, 255, 255)

    # Fallback fonts
    if not font_ar:
        font_ar = find_font([
            'Amiri-Regular.ttf',
            'NotoNaskhArabic-Regular.ttf',
            'Tahoma.ttf',
            'Arial.ttf',
            'Times.ttf',  # Times New Roman
        ]) or 'arial.ttf'  # let PIL try default
    if not font_en:
        font_en = find_font([
            'Montserrat-Regular.ttf',
            'Roboto-Regular.ttf',
            'Arial.ttf',
            'SegoeUI.ttf',
        ]) or 'arial.ttf'

    # Background
    bg = ColorClip(size=(w, h), color=(0, 0, 0), duration=duration_total).set_fps(fps)

    clips = [bg]

    def center_position(img_h: int, y: int) -> Tuple[int, int]:
        return ('center', y)

    # Anchors for layout
    y_top = int(h * 0.18)   # Top area for logos/titles
    y_text = int(h * 0.32)  # Text directly under the top area

    # Resolve logo paths (if provided/available)
    logo_azhar_path = globals().get('ARGS_LOGO_AZHAR', None)
    logo_team_path = globals().get('ARGS_LOGO_TEAM', None)
    logo_faculty_path = globals().get('ARGS_LOGO_FACULTY', None)
    logo_app_path = globals().get('ARGS_LOGO_APP', None)

    if not logo_azhar_path:
        logo_azhar_path = find_image([
            'azhar.png', 'azhar.jpg', 'azhar.jpeg',
            'alazhar.png', 'alazhar.jpg', 'alazhar.jpeg',
            'elazher.jpeg',
        ])
    if not logo_team_path:
        logo_team_path = find_image([
            'team.png', 'team.jpg', 'team.jpeg',
            'team_logo.png', 'team logo.jpg',
        ])
    if not logo_faculty_path:
        # Try common names; fallback will be engineer image if none found
        logo_faculty_path = find_image([
            'faculty.png', 'faculty.jpg', 'engineering.png', 'civil.png',
            'engineering_logo.png', 'civil_logo.png'
        ])
    if not logo_app_path:
        logo_app_path = find_image([
            'transcalc.png', 'app_logo.png', 'app.png', 'logo.png'
        ])
    # Timeline per request (16s):
    # 0–2s: black screen (no clips)

    # 2–4s: Azhar University logo (fade + golden glow)
    if logo_azhar_path and os.path.exists(logo_azhar_path):
        az_w = int(w * 0.28)
        y1 = y_top
        # Glow under
        az_glow_img = make_radial_glow_overlay(int(az_w * 1.6), int(az_w * 1.6), GOLD, strength=0.6, power=2.2)
        az_g = image_to_clip(az_glow_img, duration=2.2, fps=fps).set_start(1.9).fadein(0.6).fadeout(0.5).set_pos(('center', y1))
        clips.append(az_g)
        # Logo clip (no 3D: no zoom/rotation)
        az_logo = ImageClip(logo_azhar_path).resize(width=az_w).set_start(2.0).set_duration(2.0).fadein(0.5).fadeout(0.5)
        az_logo = az_logo.set_pos(('center', y1))
        clips.append(az_logo)
    else:
        # Fallback: show university text instead during 2–4s
        img1 = render_text_image("جامعة الأزهر", font_ar, font_size=80, color=GOLD, stroke_width=2, stroke_fill=(20, 20, 20))
        g1 = image_to_clip(glow_for_image(img1, radius=10, strength=0.6, scale=1.03), duration=2.2, fps=fps).set_start(1.9).set_pos(center_position(img1.height, y_top)).fadein(0.6).fadeout(0.5)
        clips.append(g1)
        t1 = image_to_clip(img1, duration=2.0, fps=fps).set_start(2.0).set_pos(center_position(img1.height, y_top)).fadein(0.5).fadeout(0.5)
        clips.append(t1)

    # 4–6s: University text (only)
    uni_txt = render_text_image("جامعة الأزهر", font_ar, font_size=66, color=GOLD, stroke_width=1, stroke_fill=(20, 20, 20))
    uni_glow = glow_for_image(uni_txt, radius=8, strength=0.5, scale=1.02)
    ug = image_to_clip(uni_glow, duration=2.1, fps=fps).set_start(3.9).set_pos(center_position(uni_glow.height, y_text)).fadein(0.5).fadeout(0.5)
    clips.append(ug)
    ut = image_to_clip(uni_txt, duration=2.0, fps=fps).set_start(4.0).set_pos(center_position(uni_txt.height, y_text)).fadein(0.5).fadeout(0.5)
    clips.append(ut)

    # 6–8s: Faculty logo (fade + silver glow). Fallback to engineer image
    fac_path = logo_faculty_path
    if not fac_path:
        fac_path = find_image(['engneer.jpg', 'engineer.jpg', 'engineer.jpeg', 'engineer.png'])
    if fac_path and os.path.exists(fac_path):
        fc_w = int(w * 0.26)
        y2 = y_top
        fc_glow_img = make_radial_glow_overlay(int(fc_w * 1.6), int(fc_w * 1.6), SILVER, strength=0.5, power=2.0)
        fc_g = image_to_clip(fc_glow_img, duration=2.2, fps=fps).set_start(5.9).fadein(0.5).fadeout(0.5).set_pos(('center', y2))
        clips.append(fc_g)
        fc_logo = ImageClip(fac_path).resize(width=fc_w).set_start(6.0).set_duration(2.0).fadein(0.5).fadeout(0.5)
        fc_logo = fc_logo.set_pos(('center', y2))
        clips.append(fc_logo)
    else:
        # If no logo nor engineer image: show the text instead during this slot
        tmp = render_text_image("كلية الهندسة – قسم الهندسة المدنية", font_ar, font_size=60, color=SILVER, stroke_width=1, stroke_fill=(10, 10, 10))
        tg = image_to_clip(glow_for_image(tmp, radius=8, strength=0.5, scale=1.02), duration=2.2, fps=fps).set_start(5.9).set_pos(center_position(tmp.height, y_top)).fadein(0.5).fadeout(0.5)
        clips.append(tg)
        tt = image_to_clip(tmp, duration=2.0, fps=fps).set_start(6.0).set_pos(center_position(tmp.height, y_top)).fadein(0.5).fadeout(0.5)
        clips.append(tt)

    # 8–10s: Faculty text
    fac_txt = render_text_image("كلية الهندسة – قسم الهندسة المدنية", font_ar, font_size=58, color=SILVER, stroke_width=1, stroke_fill=(10, 10, 10))
    fac_glow = glow_for_image(fac_txt, radius=8, strength=0.5, scale=1.02)
    fg = image_to_clip(fac_glow, duration=2.1, fps=fps).set_start(7.9).set_pos(center_position(fac_glow.height, y_text)).fadein(0.5).fadeout(0.5)
    clips.append(fg)
    ft = image_to_clip(fac_txt, duration=2.0, fps=fps).set_start(8.0).set_pos(center_position(fac_txt.height, y_text)).fadein(0.5).fadeout(0.5)
    clips.append(ft)

    # 10–12s: Team logo (fade + blue glow)
    if logo_team_path and os.path.exists(logo_team_path):
        tm_w = int(w * 0.26)
        y3 = y_top
        tm_glow_img = make_radial_glow_overlay(int(tm_w * 1.6), int(tm_w * 1.6), LIGHT_BLUE, strength=0.5, power=2.0)
        tm_g = image_to_clip(tm_glow_img, duration=2.2, fps=fps).set_start(9.9).fadein(0.5).fadeout(0.5).set_pos(('center', y3))
        clips.append(tm_g)
        tm_logo = ImageClip(logo_team_path).resize(width=tm_w).set_start(10.0).set_duration(2.0).fadein(0.5).fadeout(0.5)
        tm_logo = tm_logo.set_pos(('center', y3))
        clips.append(tm_logo)
    else:
        # Text fallback if team logo missing
        tmp = render_text_image("Geo Mapper Team", font_en, font_size=72, color=LIGHT_BLUE, stroke_width=0)
        tg = image_to_clip(glow_for_image(tmp, radius=8, strength=0.45, scale=1.03), duration=2.2, fps=fps).set_start(9.9).set_pos(center_position(tmp.height, y_top)).fadein(0.4).fadeout(0.4)
        clips.append(tg)
        tt = image_to_clip(tmp, duration=2.0, fps=fps).set_start(10.0).set_pos(center_position(tmp.height, y_top)).fadein(0.3).fadeout(0.3)
        clips.append(tt)

    # 12–14s: Team text
    team_txt = render_text_image("Geo Mapper Team", font_en, font_size=66, color=LIGHT_BLUE, stroke_width=0)
    team_glow = glow_for_image(team_txt, radius=8, strength=0.45, scale=1.02)
    tg2 = image_to_clip(team_glow, duration=2.1, fps=fps).set_start(11.9).set_pos(center_position(team_glow.height, y_text)).fadein(0.5).fadeout(0.5)
    clips.append(tg2)
    tt2 = image_to_clip(team_txt, duration=2.0, fps=fps).set_start(12.0).set_pos(center_position(team_txt.height, y_text)).fadein(0.5).fadeout(0.5)
    clips.append(tt2)

    # 14–16s: Fade to black handled by final fadeout

    # Overlays: subtle animated noise and vignette on top for cinematic look
    noise_clip = make_noise_clip(w, h, duration_total, fps=fps, opacity=0.035)
    noise_clip = noise_clip.set_start(0)
    clips.append(noise_clip)

    vignette = create_vignette_clip(w, h, duration_total, strength=0.3, power=2.2, fps=fps)
    vignette = vignette.set_start(0)
    clips.append(vignette)

    final = CompositeVideoClip(clips, size=(w, h)).set_duration(duration_total)
    # Global fadeout for last 2 seconds (14–16s)
    final = final.fx(vfx.fadeout, 2.0)

    # Audio (optional)
    if music_path and os.path.exists(music_path):
        try:
            audio = AudioFileClip(music_path).fx(lambda a: a)
            # trim or loop to total duration
            if audio.duration < duration_total:
                audio = audio.set_end(duration_total)
            else:
                audio = audio.subclip(0, duration_total)
            # fade in/out
            audio = audio.audio_fadein(2.0).audio_fadeout(4.0)
            final = final.set_audio(audio)
        except Exception as e:
            print(f"[WARN] Failed to load audio: {e}")

    # Ensure output directory
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)

    print(f"[INFO] Rendering video to {out_path} ...")
    final.write_videofile(
        out_path,
        fps=fps,
        codec='libx264',
        audio_codec='aac',
        preset='slow',
        threads=os.cpu_count() or 4,
        temp_audiofile='temp-audio.m4a',
        remove_temp=True,
        verbose=False,
        logger=None,
        ffmpeg_params=[
            '-crf', '17',
            '-profile:v', 'high',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-b:a', '192k',
        ],
    )
    print("[OK] Done.")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description='Render a simple 20s intro video (black background, fading texts).')
    p.add_argument('--out', default='intro.mp4', help='Output video file path (mp4).')
    p.add_argument('--music', default=None, help='Optional music file (wav/mp3).')
    p.add_argument('--w', type=int, default=1920, help='Width in pixels (default 1920).')
    p.add_argument('--h', type=int, default=1080, help='Height in pixels (default 1080).')
    p.add_argument('--fps', type=int, default=30, help='Frames per second (default 30).')
    p.add_argument('--font_ar', default=None, help='Path to Arabic-supporting TTF (e.g., Tahoma.ttf, Amiri-Regular.ttf).')
    p.add_argument('--font_en', default=None, help='Path to Latin TTF (e.g., Arial.ttf, Roboto-Regular.ttf).')
    p.add_argument('--logo_azhar', default=None, help='Path to Azhar University logo image (png/jpg).')
    p.add_argument('--logo_faculty', default=None, help='Path to Faculty (Engineering/Civil) logo image (png/jpg).')
    p.add_argument('--logo_team', default=None, help='Path to Team logo image (png/jpg).')
    p.add_argument('--logo_app', default=None, help='Path to App/TransCalc logo image (png/jpg).')
    return p.parse_args(argv)


if __name__ == '__main__':
    args = parse_args()
    # Store CLI logo args in globals for build_intro resolution
    ARGS_LOGO_AZHAR = args.logo_azhar
    ARGS_LOGO_FACULTY = args.logo_faculty
    ARGS_LOGO_TEAM = args.logo_team
    ARGS_LOGO_APP = args.logo_app
    build_intro(
        out_path=args.out,
        music_path=args.music,
        w=args.w,
        h=args.h,
        fps=args.fps,
        font_ar=args.font_ar,
        font_en=args.font_en,
    )
