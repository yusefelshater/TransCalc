"""
GUI for Pavement Performance Model using customtkinter
with interactive charts (matplotlib) in the Results tab.

Integrated with TransCalc catalog costing via model.calculate_mix and
export through exporter.export_run.

New features:
- Validation warnings for bitumen/rubber ranges and aggregates normalization.
- Overheads Panel to choose mode (Percent/Per Ton/Hybrid) and edit values.
- Scenario Runner tab to compare Baseline vs Scenario and show savings.
"""
import customtkinter as ctk
from tkinter import messagebox, filedialog
from model import run_model, calculate_mix
import json
import os
import sys
import shutil
import subprocess
from datetime import datetime
from typing import Any, Dict
import webbrowser
from pathlib import Path

# Planner integration
try:
    from planner import analyze_path as planner_analyze_path, load_geojson_path as planner_load_geojson_path, DEFAULT_WEIGHTS as PL_DEFAULT_WEIGHTS, slice_path_segment as planner_slice_path_segment
    PLANNER_AVAILABLE = True
except Exception:
    PLANNER_AVAILABLE = False

# Optional matplotlib imports for plotting
try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.pyplot as plt
    MATPLOT_AVAILABLE = True
except Exception:  # ImportError or backend issues
    MATPLOT_AVAILABLE = False

# Optional hover tooltips for matplotlib
try:
    import mplcursors
    MPLCURS_AVAILABLE = True
except Exception:
    MPLCURS_AVAILABLE = False

# Unified color palette
PALETTE = {
    "costs": {
        "aggregate": "#58a6ff",
        "bitumen": "#ff7b72",
        "plastic": "#2ea043",
        "rubber": "#c297ff",
        "overhead": "#f2cc60",
    },
    "life": {
        "fatigue": "#7ee787",
        "rutting": "#ffcc66",
        "design": "#79c0ff",
    },
    "warn_bg": "#3b2f00",
    "warn_text": "#ffd166",
}

STANDARDS_PATH = os.path.join(os.path.dirname(__file__), "standards.json")
COSTS_PATH = os.path.join(os.path.dirname(__file__), "costs.json")

# Exporter (for XLSX/JSON runs)
try:
    from exporter import export_run as exporter_export_run, export_json as exporter_export_json, export_planner as exporter_export_planner
except Exception:
    exporter_export_run = None  # type: ignore
    exporter_export_json = None  # type: ignore
    exporter_export_planner = None  # type: ignore

class PavementApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Configure window
        self.title("Pavement Performance Model")
        self.geometry("1000x700")
        ctk.set_appearance_mode("dark")  # Modes: "System", "Dark", "Light"
        # Hide window initially to play intro seamlessly
        try:
            self.withdraw()
        except Exception:
            pass
        
        # Load standards presets (if available)
        self.standards = self.load_standards()
        self.ui_lock_inputs = bool(self.standards.get("ui", {}).get("lock_inputs_until_preset_selected", True))
        self.current_preset = None
        self.current_coeffs = {}
        self.current_ranges = None
        self.last_results = None
        self.last_inputs_export = None
        # Catalog for TransCalc costing and last mix inputs/results
        self.catalog = self.load_catalog()
        self.last_mix_inputs: Dict[str, Any] | None = None
        self.last_mix_results: Dict[str, Any] | None = None
        
        # Create sidebar
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        
        # Sidebar widgets
        self.logo_label = ctk.CTkLabel(self.sidebar, text="ME-lite", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.pack(pady=20, padx=10)
        
        # Preset buttons
        self.btn_eg = ctk.CTkButton(self.sidebar, text="Egyptian", command=lambda: self.apply_preset("egyptian"))
        self.btn_us = ctk.CTkButton(self.sidebar, text="American", command=lambda: self.apply_preset("american"))
        self.btn_custom = ctk.CTkButton(self.sidebar, text="Custom", command=lambda: self.apply_preset("custom_template"))
        self.btn_eg.pack(pady=(0, 6), padx=20, fill="x")
        self.btn_us.pack(pady=6, padx=20, fill="x")
        self.btn_custom.pack(pady=6, padx=20, fill="x")

        # Quick navigation to Overheads tab
        self.btn_overheads = ctk.CTkButton(self.sidebar, text="Overheads", command=self.navigate_to_overheads)
        self.btn_overheads.pack(pady=(0, 6), padx=20, fill="x")

        self.run_button = ctk.CTkButton(self.sidebar, text="Run Model", command=self.run_model)
        self.run_button.pack(pady=10, padx=20, fill="x")

        self.export_button = ctk.CTkButton(self.sidebar, text="Export Run", command=self.export_run)
        self.export_button.pack(pady=(0, 10), padx=20, fill="x")
        self.export_button.configure(state="disabled")
        
        # Create main content area
        self.main_frame = ctk.CTkFrame(self, corner_radius=0)
        self.main_frame.pack(side="right", fill="both", expand=True)
        
        # Create tabs
        self.tabs = ctk.CTkTabview(self.main_frame)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Inputs tab
        self.inputs_tab = self.tabs.add("Inputs")
        self.create_inputs(self.inputs_tab)
        
        # Overheads tab
        self.overheads_tab = self.tabs.add("Overheads")
        self.create_overheads_panel(self.overheads_tab)

        # Results tab
        self.results_tab = self.tabs.add("Results")
        self.create_results(self.results_tab)
        
        # Warnings tab
        self.warnings_tab = self.tabs.add("Warnings")
        self.warnings_text = ctk.CTkTextbox(self.warnings_tab, wrap="word")
        self.warnings_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.warnings_text.configure(state="disabled")
        
        # Scenarios tab
        self.scenarios_tab = self.tabs.add("Scenarios")
        self.create_scenarios(self.scenarios_tab)

        # Planner tab
        self.planner_tab = self.tabs.add("Planner")
        self.create_planner(self.planner_tab)
        
        # Schedule intro playback, then show the main window
        self.after(100, self.play_intro_then_show)

    # ---------------------- Intro Playback ----------------------
    def app_dir(self) -> str:
        return os.path.dirname(__file__)

    def get_intro_video_path(self) -> str | None:
        """Return a preferred intro video path if it exists, else None."""
        candidates = [
            os.path.join(self.app_dir(), "intro.mp4"),
            os.path.join(self.app_dir(), "runs", "intro.mp4"),
            os.path.join(self.app_dir(), "runs", "intro_4k60.mp4"),
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def find_ffplay(self) -> str | None:
        """Return an ffplay executable path if available.
        Checks PATH, FFPLAY_PATH env, and common Windows install locations.
        """
        # PATH
        p = shutil.which("ffplay")
        if p:
            return p
        # Env var override
        env_p = os.environ.get("FFPLAY_PATH")
        if env_p and os.path.exists(env_p):
            return env_p
        # Common Windows locations
        candidates = [
            os.path.join(self.app_dir(), "ffmpeg", "bin", "ffplay.exe"),
            os.path.join(self.app_dir(), "bin", "ffplay.exe"),
            r"C:\\ffmpeg\\bin\\ffplay.exe",
            r"C:\\Program Files\\ffmpeg\\bin\\ffplay.exe",
            r"C:\\Program Files\\FFmpeg\\bin\\ffplay.exe",
            os.path.expanduser(r"~\\scoop\\apps\\ffmpeg\\current\\bin\\ffplay.exe"),
            r"C:\\ProgramData\\chocolatey\\bin\\ffplay.exe",
        ]
        for c in candidates:
            try:
                if os.path.exists(c) and os.access(c, os.X_OK):
                    return c
            except Exception:
                continue
        return None

    def find_vlc(self) -> str | None:
        """Return a VLC executable path if available.
        Checks PATH, VLC_PATH env, and common Windows locations.
        """
        p = shutil.which("vlc")
        if p:
            return p
        env_p = os.environ.get("VLC_PATH")
        if env_p and os.path.exists(env_p):
            return env_p
        candidates = [
            r"C:\\Program Files\\VideoLAN\\VLC\\vlc.exe",
            r"C:\\Program Files (x86)\\VideoLAN\\VLC\\vlc.exe",
        ]
        for c in candidates:
            try:
                if os.path.exists(c) and os.access(c, os.X_OK):
                    return c
            except Exception:
                continue
        return None

    def get_intro_duration_seconds(self) -> float:
        """Intro duration to wait when launching with default OS player."""
        return 16.0

    def play_intro_then_show(self):
        """Play intro using default player; wait its duration, then show GUI.
        Prefer ffplay if available because it blocks until finish.
        """
        # Hide GUI while intro is playing
        try:
            self.withdraw()
        except Exception:
            pass
        video = self.get_intro_video_path()
        ffplay_path = self.find_ffplay()
        if video:
            try:
                if ffplay_path:
                    # Fullscreen, auto-exit, minimal logs (blocking until done)
                    try:
                        sw, sh = int(self.winfo_screenwidth()), int(self.winfo_screenheight())
                    except Exception:
                        sw, sh = 1920, 1080
                    vf = f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh}"
                    args = [
                        ffplay_path,
                        "-hide_banner",
                        "-loglevel", "error",
                        "-autoexit",
                        "-fs",
                        "-noborder",
                        "-alwaysontop",
                        "-vf", vf,
                        video,
                    ]
                    res = subprocess.run(args, check=False)
                    if res.returncode != 0:
                        # Retry without extra window flags for broader compatibility
                        fallback_args = [
                            ffplay_path,
                            "-hide_banner",
                            "-loglevel", "error",
                            "-autoexit",
                            "-fs",
                            "-vf", vf,
                            video,
                        ]
                        subprocess.run(fallback_args, check=False)
                    self.safe_show()
                    return
                # Fallback 1: try VLC explicitly in fullscreen without UI, and wait until exit
                vlc_path = self.find_vlc()
                if vlc_path:
                    vlc_args = [
                        vlc_path,
                        "-I", "dummy",  # no GUI controls
                        "--fullscreen",
                        "--no-video-title-show",
                        "--play-and-exit",
                        "--quiet",
                        "--video-on-top",
                        video,
                    ]
                    subprocess.run(vlc_args, check=False)
                    self.safe_show()
                    return
                # Fallback 2: ask user to locate ffplay.exe or vlc.exe to avoid borders
                try:
                    selected = filedialog.askopenfilename(
                        title="Select ffplay.exe or vlc.exe for fullscreen intro (no borders)",
                        filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
                    )
                except Exception:
                    selected = ""
                if selected:
                    base = os.path.basename(selected).lower()
                    if base == "ffplay.exe":
                        ffplay_path = selected
                        # Re-run ffplay path
                        try:
                            sw, sh = int(self.winfo_screenwidth()), int(self.winfo_screenheight())
                        except Exception:
                            sw, sh = 1920, 1080
                        vf = f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh}"
                        args = [
                            ffplay_path,
                            "-hide_banner",
                            "-loglevel", "error",
                            "-autoexit",
                            "-fs",
                            "-noborder",
                            "-alwaysontop",
                            "-vf", vf,
                            video,
                        ]
                        subprocess.run(args, check=False)
                        self.safe_show()
                        return
                    if base == "vlc.exe":
                        vlc_args = [
                            selected,
                            "-I", "dummy",
                            "--fullscreen",
                            "--no-video-title-show",
                            "--play-and-exit",
                            "--quiet",
                            "--video-on-top",
                            video,
                        ]
                        subprocess.run(vlc_args, check=False)
                        self.safe_show()
                        return
                # Final fallback removed to avoid bordered players. Show GUI directly.
                try:
                    messagebox.showinfo(
                        "Intro player not found",
                        "Couldn't find ffplay or VLC for borderless fullscreen. "
                        "Install FFmpeg (ffplay) or VLC, or pick the executable when prompted. "
                        "Proceeding to the app without playing the intro.",
                    )
                except Exception:
                    pass
                self.safe_show()
                return
            except Exception:
                pass
        # No video or failed playback; show immediately
        self.safe_show()

    def safe_show(self):
        try:
            self.deiconify()
        except Exception:
            pass

    # ---------------------- Navigation Helpers ----------------------
    def navigate_to_overheads(self):
        """Switch to Overheads tab and focus the first right-column entry (EGP/ton)."""
        try:
            self.tabs.set("Overheads")
        except Exception:
            return
        # Defer focus slightly until widgets are realized
        def _focus():
            try:
                # Prefer the second right entry if available, else the first
                target = None
                if hasattr(self, "ovh_second_entry_right") and self.ovh_second_entry_right is not None:
                    target = self.ovh_second_entry_right
                elif hasattr(self, "ovh_first_entry_right") and self.ovh_first_entry_right is not None:
                    target = self.ovh_first_entry_right
                if target is not None:
                    target.focus_set()
                    try:
                        target.icursor("end")
                    except Exception:
                        pass
            except Exception:
                pass
        self.after(60, _focus)
        
    def create_inputs(self, tab):
        """Create input fields in the inputs tab"""
        # Define input parameters
        self.params = {
            "L": {"label": "Road Length (km)", "default": "1.0"},
            "W": {"label": "Road Width (m)", "default": "3.5"},
            "h": {"label": "Layer Thickness (m)", "default": "0.05"},
            "rho_m": {"label": "Mixture Density (ton/m³)", "default": "2.4"},
            "Pb": {"label": "Bitumen Content (proportion)", "default": "0.055"},
            "Pp": {"label": "Plastic Content (proportion of bitumen)", "default": "0.05"},
            "Pr": {"label": "Rubber Content (proportion of bitumen)", "default": "0.08"},
            "T": {"label": "Temperature (°C)", "default": "30.0"},
            "A": {"label": "Annual ESALs (millions)", "default": "1.0"},
            "c_agg": {"label": "Aggregate Cost (per ton)", "default": "100.0"},
            "c_bit": {"label": "Bitumen Cost (per ton)", "default": "500.0"},
            "c_pl": {"label": "Plastic Cost (per ton)", "default": "200.0"},
            "c_rub": {"label": "Rubber Cost (per ton)", "default": "300.0"},
            "overhead": {"label": "Overhead Cost", "default": "1000.0"},
            "target_design_life": {"label": "Target Design Life (years)", "default": "15"}
        }
        
        self.entries = {}
        scroll_frame = ctk.CTkScrollableFrame(tab)
        scroll_frame.pack(fill="both", expand=True)
        
        for i, (key, data) in enumerate(self.params.items()):
            # Create frame for each input
            frame = ctk.CTkFrame(scroll_frame)
            frame.pack(fill="x", padx=10, pady=5)
            
            # Create label
            label = ctk.CTkLabel(frame, text=data["label"], width=200)
            label.pack(side="left", padx=(0, 10))
            
            # Create entry
            entry = ctk.CTkEntry(frame)
            entry.insert(0, data["default"])
            entry.pack(side="right", fill="x", expand=True)
            self.entries[key] = entry
            # If user clicks the legacy 'overhead' field, navigate to Overheads tab instead
            if key == "overhead":
                try:
                    entry.bind("<Button-1>", self.on_overhead_entry_click)
                    entry.bind("<FocusIn>", self.on_overhead_entry_click)
                    # Optional: make it read-only to encourage editing in Overheads panel
                    # entry.configure(state="readonly")
                except Exception:
                    pass

        # Lock inputs and Run button until preset selected (if configured)
        if self.ui_lock_inputs:
            self.set_inputs_state("disabled")
            self.run_button.configure(state="disabled")

    def on_overhead_entry_click(self, event=None):
        """Redirect clicks/focus on legacy overhead field to the Overheads tab.
        Returns 'break' to stop editing in this field.
        """
        try:
            self.navigate_to_overheads()
        finally:
            return "break"

    # ---------------------- Catalog Loader ----------------------
    def load_catalog(self) -> dict:
        try:
            with open(COSTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def build_mix_inputs_from_gui(self) -> dict:
        """
        Build TransCalc calculate_mix inputs using GUI fields for project and binder,
        and baseline aggregates/overheads from costs.json when available.
        """
        # Read current GUI entries (use defaults if missing)
        try:
            L = float(self.entries.get("L").get())
            W = float(self.entries.get("W").get())
            h = float(self.entries.get("h").get())
            rho = float(self.entries.get("rho_m").get())
            Pb = float(self.entries.get("Pb").get())
            Pr = float(self.entries.get("Pr").get())
        except Exception:
            # Fallback to minimal safe defaults
            L, W, h, rho, Pb, Pr = 1.0, 7.0, 0.05, 2.35, 0.055, 0.02

        catalog = self.catalog if isinstance(self.catalog, dict) else {}
        baseline = (catalog.get("baseline") or {}) if isinstance(catalog, dict) else {}
        mixb = (baseline.get("mix") or {}) if isinstance(baseline, dict) else {}
        agg_cfg = (mixb.get("aggregates") or {}) if isinstance(mixb, dict) else {}

        aggregates_shares = {
            "coarse": ((agg_cfg.get("coarse") or {}).get("fraction_of_mix") or 0.0),
            "medium": ((agg_cfg.get("medium") or {}).get("fraction_of_mix") or 0.0),
            "fine": ((agg_cfg.get("fine") or {}).get("fraction_of_mix") or 0.0),
        }
        aggregates_type_ids = {
            "coarse": ((agg_cfg.get("coarse") or {}).get("type_id")),
            "medium": ((agg_cfg.get("medium") or {}).get("type_id")),
            "fine": ((agg_cfg.get("fine") or {}).get("type_id")),
        }

        # Overheads: read from UI if available, else fall back to catalog defaults
        ovh_inputs = self.read_current_overheads_from_ui()
        if not ovh_inputs:
            ovh_cfg = (catalog.get("overheads") or {}) if isinstance(catalog, dict) else {}
            comps_out = []
            comps = ovh_cfg.get("components") if isinstance(ovh_cfg, dict) else None
            if isinstance(comps, list):
                for comp in comps:
                    if not isinstance(comp, dict):
                        continue
                    d = comp.get("default", {}) or {}
                    comps_out.append({
                        "id": comp.get("id"),
                        "percent": d.get("percent"),
                        "egp_per_ton": d.get("egp_per_ton"),
                    })
            ovh_inputs = {
                "mode": ovh_cfg.get("mode", "percent"),
                "components": comps_out,
            }

        return {
            "project": {
                "length_km": L,
                "width_m": W,
                "thickness_m": h,
                "density_ton_per_m3": rho,
            },
            "mix": {
                "bitumen_prop_of_mix": Pb,
                "rubber_prop_of_bitumen": Pr,
                "aggregates_shares": aggregates_shares,
                "aggregates_type_ids": aggregates_type_ids,
            },
            "overheads": ovh_inputs,
        }
    
    def create_results(self, tab):
        """Create results display and plots in the results tab"""
        # Numeric results area
        self.results_text = ctk.CTkTextbox(tab, wrap="word", height=130)
        self.results_text.pack(fill="x", padx=10, pady=(10, 0))
        self.results_text.configure(state="disabled")

        # KPI cards container
        self.kpi_frame = ctk.CTkFrame(tab)
        self.kpi_frame.pack(fill="x", padx=10, pady=10)
        self.kpi_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="kpi")

        def create_card(parent, title):
            card = ctk.CTkFrame(parent, corner_radius=8)
            title_lbl = ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12, weight="bold"))
            value_lbl = ctk.CTkLabel(card, text="—", font=ctk.CTkFont(size=18, weight="bold"))
            title_lbl.pack(pady=(10, 0))
            value_lbl.pack(pady=(2, 10))
            return card, value_lbl

        self.card_total, self.card_total_value = create_card(self.kpi_frame, "Total Cost (EGP)")
        self.card_m2, self.card_m2_value = create_card(self.kpi_frame, "Cost per m² (EGP)")
        self.card_life, self.card_life_value = create_card(self.kpi_frame, "Design Life (years)")
        self.card_total.grid(row=0, column=0, padx=6, sticky="nsew")
        self.card_m2.grid(row=0, column=1, padx=6, sticky="nsew")
        self.card_life.grid(row=0, column=2, padx=6, sticky="nsew")

        # Plot container
        self.plot_container = ctk.CTkFrame(tab)
        self.plot_container.pack(fill="both", expand=True, padx=10, pady=10)

        # Inline warnings box
        self.inline_warn = ctk.CTkFrame(tab, fg_color=PALETTE["warn_bg"], corner_radius=6)
        self.inline_warn.pack(fill="x", padx=10, pady=(0, 10))
        warn_title = ctk.CTkLabel(self.inline_warn, text="Warnings", font=ctk.CTkFont(size=12, weight="bold"), text_color=PALETTE["warn_text"]) 
        warn_title.pack(anchor="w", padx=10, pady=(8, 0))
        self.inline_warn_label = ctk.CTkLabel(self.inline_warn, text="No warnings", text_color=PALETTE["warn_text"])
        self.inline_warn_label.pack(anchor="w", padx=10, pady=(2, 8))

        # Placeholder if matplotlib not available
        if not MATPLOT_AVAILABLE:
            self.plot_placeholder = ctk.CTkLabel(
                self.plot_container,
                text="Matplotlib غير مثبت. لتفعيل الرسوم: pip install matplotlib",
            )
            self.plot_placeholder.pack(pady=20)
        else:
            self.plot_placeholder = None
        self.canvas = None  # will be created on first run
        
    def run_model(self):
        """Run the model with input parameters"""
        # Collect input values
        input_values = {}
        for key, entry in self.entries.items():
            input_values[key] = float(entry.get())
        
        # Get target design life
        target_design_life = input_values.pop("target_design_life")
        
        # Pre-validate key mix inputs and collect warnings (GUI-level safety)
        gui_warnings = []
        try:
            Pb = float(self.entries.get("Pb").get())
            Pr = float(self.entries.get("Pr").get())
        except Exception:
            Pb, Pr = None, None
        # Reset entry colors (best-effort)
        try:
            self.entries["Pb"].configure(border_color=None)
            self.entries["Pr"].configure(border_color=None)
        except Exception:
            pass
        if isinstance(Pb, float) and not (0.04 <= Pb <= 0.07):
            gui_warnings.append("تنبيه: نسبة البيتومين يجب أن تكون بين 4% و7%.")
            try:
                self.entries["Pb"].configure(border_color="#ff4d4f")
            except Exception:
                pass
        if isinstance(Pr, float) and not (0.01 <= Pr <= 0.60):
            gui_warnings.append("تنبيه: نسبة المطاط (من البيتومين) يجب أن تكون بين 1% و60%.")
            try:
                self.entries["Pr"].configure(border_color="#ff4d4f")
            except Exception:
                pass
        # Prefer overheads from Overheads tab (TransCalc) to keep results consistent
        mix_res = None
        try:
            mix_inputs = self.build_mix_inputs_from_gui()
            mix_res = calculate_mix(mix_inputs, self.catalog or {})
            # Override legacy overhead with catalog-overheads total for consistency
            ovh_total = float(((mix_res.get("costs") or {}).get("overhead_total", 0.0)) or 0.0)
            input_values["overhead"] = ovh_total
        except Exception as e_mix:
            # Non-fatal: continue with legacy overhead field
            try:
                messagebox.showwarning("Catalog Costing", f"تعذّر حساب كلفة الكتالوج: {e_mix}\nسيُستخدم حقل Overhead في تبويب Inputs مؤقتًا.")
            except Exception:
                pass

        # Run the performance model (legacy) using possibly overridden overhead
        try:
            results = run_model(
                **input_values,
                target_design_life=target_design_life,
                coeffs=self.current_coeffs or {},
                allowed_ranges=self.current_ranges,
            )
            # If we have mix_res, attach and align totals to show consistent overhead in Results
            if isinstance(mix_res, dict):
                results["mix_results"] = mix_res
                self.last_mix_inputs = mix_inputs
                self.last_mix_results = mix_res
                # Merge warnings
                try:
                    merged_w = list(results.get("warnings", []) or []) + gui_warnings + list(mix_res.get("warnings", []) or [])
                    results["warnings"] = merged_w
                except Exception:
                    pass
                # Align legacy result totals with catalog overhead for consistency in UI
                try:
                    ovh_total = float(((mix_res.get("costs") or {}).get("overhead_total", 0.0)) or 0.0)
                    material_cost = float(results.get("material_cost", 0.0))
                    results["total_cost"] = material_cost + ovh_total
                    # Recompute per-area/ton
                    area = float(self.entries.get("L").get()) * 1000.0 * float(self.entries.get("W").get())
                    area = max(1e-9, area)
                    total_mass = float(results.get("total_mass_ton", results.get("coefficients_effective", {}).get("dummy", 0.0)))
                    # If total_mass_ton not available in legacy path, recompute quickly
                    if not isinstance(total_mass, float) or total_mass <= 0.0:
                        # V = L(km)*1000*W*h ; M = V * rho_m
                        try:
                            L = float(self.entries.get("L").get())
                            W = float(self.entries.get("W").get())
                            h = float(self.entries.get("h").get())
                            rho = float(self.entries.get("rho_m").get())
                            V = L * 1000.0 * W * h
                            total_mass = V * rho
                        except Exception:
                            total_mass = 1.0
                    results["cost_per_m2"] = results["total_cost"] / area
                    results["cost_per_ton"] = results["total_cost"] / max(1e-9, total_mass)
                    # Also reflect overhead in nested costs map if present
                    if isinstance(results.get("costs"), dict):
                        results["costs"]["overhead"] = ovh_total
                        results["costs"]["total_cost"] = results["total_cost"]
                except Exception:
                    pass
            else:
                # No mix_res: still add GUI warnings if any
                try:
                    merged_w = list(results.get("warnings", []) or []) + gui_warnings
                    results["warnings"] = merged_w
                except Exception:
                    pass

            # keep last run context for export
            self.last_results = results
            self.last_inputs_export = self.build_export_inputs(input_values, target_design_life)

            # Enable export after a successful run
            self.export_button.configure(state="normal")
            self.display_results(results)
            self.display_warnings(results.get("warnings", []))
            self.update_kpis(results)
            self.update_plots(results)
            self.display_warnings_inline(results.get("warnings", []))
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------------------- Overheads Panel ----------------------
    def create_overheads_panel(self, tab):
        catalog = self.catalog if isinstance(self.catalog, dict) else {}
        ovh_cfg = (catalog.get("overheads") or {}) if isinstance(catalog, dict) else {}
        comps = ovh_cfg.get("components") if isinstance(ovh_cfg, dict) else []

        self.ovh_mode_var = ctk.StringVar(value=ovh_cfg.get("mode", "percent"))
        self.ovh_percent_vars: dict[str, ctk.StringVar] = {}
        self.ovh_perton_vars: dict[str, ctk.StringVar] = {}
        # Keep entry widgets to enable/disable per mode
        self.ovh_percent_entries: dict[str, ctk.CTkEntry] = {}
        self.ovh_perton_entries: dict[str, ctk.CTkEntry] = {}
        # Ordered lists to control focus (left/right columns)
        self.ovh_left_entries_order: list[ctk.CTkEntry] = []
        self.ovh_right_entries_order: list[ctk.CTkEntry] = []
        self.ovh_first_entry_left = None
        self.ovh_second_entry_right = None
        # ovh_first_entry_right is set later and used by navigation helper

        container = ctk.CTkScrollableFrame(tab)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Mode selection
        mode_frame = ctk.CTkFrame(container)
        mode_frame.pack(fill="x", padx=6, pady=(0, 10))
        ctk.CTkLabel(mode_frame, text="Overheads Mode", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=8)
        for txt, val in [("Percent", "percent"), ("Per Ton", "per_ton"), ("Hybrid", "hybrid")]:
            rb = ctk.CTkRadioButton(mode_frame, text=txt, variable=self.ovh_mode_var, value=val, command=self.on_ovh_mode_change)
            rb.pack(side="left", padx=6)

        # Components grid
        grid = ctk.CTkFrame(container)
        grid.pack(fill="x", padx=6, pady=6)
        header = ctk.CTkFrame(grid)
        header.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(header, text="البند", width=160).pack(side="left", padx=4)
        ctk.CTkLabel(header, text="النسبة (مثال 0.10)", width=160).pack(side="left", padx=4)
        ctk.CTkLabel(header, text="جنيه/طن", width=160).pack(side="left", padx=4)

        for comp in (comps or []):
            if not isinstance(comp, dict):
                continue
            cid = str(comp.get("id"))
            label = str(comp.get("label", cid))
            d = comp.get("default", {}) or {}
            p_var = ctk.StringVar(value=str(d.get("percent", "")))
            v_var = ctk.StringVar(value=str(d.get("egp_per_ton", "")))
            self.ovh_percent_vars[cid] = p_var
            self.ovh_perton_vars[cid] = v_var

            row = ctk.CTkFrame(grid)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=label, width=160).pack(side="left", padx=4)
            e1 = ctk.CTkEntry(row, textvariable=p_var)
            e1.pack(side="left", padx=4, fill="x", expand=True)
            e2 = ctk.CTkEntry(row, textvariable=v_var)
            e2.pack(side="left", padx=4, fill="x", expand=True)

            # Remember the first right-column entry to focus when navigating here
            if not hasattr(self, "ovh_first_entry_right") or self.ovh_first_entry_right is None:
                self.ovh_first_entry_right = e2
            if self.ovh_first_entry_left is None:
                self.ovh_first_entry_left = e1

            # Store entries for state control
            self.ovh_percent_entries[cid] = e1
            self.ovh_perton_entries[cid] = e2
            # Keep order for focus targets
            self.ovh_left_entries_order.append(e1)
            self.ovh_right_entries_order.append(e2)
            if self.ovh_second_entry_right is None and len(self.ovh_right_entries_order) >= 2:
                self.ovh_second_entry_right = self.ovh_right_entries_order[1]

        # Hint footer
        hint = ctk.CTkLabel(container, text=(
            "اختَر النمط: Percent (جمع نسب × تكلفة المواد) / Per Ton (قيمة × طن الخلطة) / Hybrid (الاثنين).\n"
            "تُستخدم هذه القيم في الحسابات فور الضغط على Run Model أو عند المقارنة في تبويب Scenarios."
        ))
        hint.pack(fill="x", padx=6, pady=(6, 0))

        # Apply initial enable/disable state according to current mode
        self.on_ovh_mode_change()

    def read_current_overheads_from_ui(self) -> dict | None:
        try:
            mode = self.ovh_mode_var.get() if hasattr(self, "ovh_mode_var") else None
        except Exception:
            mode = None
        if not mode:
            return None
        comps = []
        try:
            for cid, p_var in (self.ovh_percent_vars or {}).items():
                # align per-ton var by same id
                v_var = (self.ovh_perton_vars or {}).get(cid)
                p = None
                v = None
                try:
                    p_val = p_var.get().strip()
                    if p_val != "":
                        p = float(p_val)
                except Exception:
                    p = None
                try:
                    v_val = v_var.get().strip() if v_var else ""
                    if v_val != "":
                        v = float(v_val)
                except Exception:
                    v = None
                comps.append({"id": cid, "percent": p, "egp_per_ton": v})
        except Exception:
            comps = []
        return {"mode": mode, "components": comps}

    def on_ovh_mode_change(self):
        """Enable/disable columns based on selected overheads mode and focus the relevant column."""
        try:
            mode = self.ovh_mode_var.get()
        except Exception:
            mode = "percent"
        # States per mode
        def set_state(entry, enabled: bool):
            try:
                entry.configure(state="normal" if enabled else "disabled")
            except Exception:
                pass
        # Toggle entries
        for cid, e in (self.ovh_percent_entries or {}).items():
            set_state(e, mode in ("percent", "hybrid"))
        for cid, e in (self.ovh_perton_entries or {}).items():
            set_state(e, mode in ("per_ton", "hybrid"))
        # Focus appropriate first entry
        try:
            if mode == "percent" and self.ovh_first_entry_left is not None:
                self.ovh_first_entry_left.focus_set()
                try:
                    self.ovh_first_entry_left.icursor("end")
                except Exception:
                    pass
            elif mode == "per_ton":
                target = None
                if hasattr(self, "ovh_second_entry_right") and self.ovh_second_entry_right is not None:
                    target = self.ovh_second_entry_right
                elif hasattr(self, "ovh_first_entry_right") and self.ovh_first_entry_right is not None:
                    target = self.ovh_first_entry_right
                if target is not None:
                    target.focus_set()
                    try:
                        target.icursor("end")
                    except Exception:
                        pass
        except Exception:
            pass

    # ---------------------- Scenarios Runner ----------------------
    def create_scenarios(self, tab):
        container = ctk.CTkScrollableFrame(tab)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # Action button
        action_frame = ctk.CTkFrame(container)
        action_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(action_frame, text="Baseline vs Scenario", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left", padx=8)
        ctk.CTkButton(action_frame, text="Compare Now", command=self.run_scenario_compare).pack(side="right", padx=8)

        # Table-like layout
        table = ctk.CTkFrame(container)
        table.pack(fill="x", padx=6, pady=6)
        # headers
        header = ctk.CTkFrame(table)
        header.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(header, text="البند", width=200, font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(header, text="Baseline", width=160, font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(header, text="Scenario", width=160, font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkLabel(header, text="الفرق", width=160, font=ctk.CTkFont(weight="bold")).pack(side="left")

        # rows: store labels for updates
        self.sc_rows = {}
        def mk_row(name):
            row = ctk.CTkFrame(table)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=name, width=200).pack(side="left")
            b = ctk.CTkLabel(row, text="—", width=160)
            s = ctk.CTkLabel(row, text="—", width=160)
            d = ctk.CTkLabel(row, text="—", width=160)
            b.pack(side="left")
            s.pack(side="left")
            d.pack(side="left")
            self.sc_rows[name] = (b, s, d)

        for name in [
            "Grand Total (EGP)",
            "Materials Subtotal (EGP)",
            "Overheads Total (EGP)",
            "Bitumen (EGP)",
            "Aggregates (EGP)",
            "Rubber (EGP)",
            "Cost per m² (EGP/m²)",
        ]:
            mk_row(name)

        # Savings summary
        summary = ctk.CTkFrame(container)
        summary.pack(fill="x", padx=6, pady=10)
        self.sav_abs_lbl = ctk.CTkLabel(summary, text="التوفير: — جنيه")
        self.sav_pct_lbl = ctk.CTkLabel(summary, text="التوفير: — %")
        self.sav_abs_lbl.pack(anchor="w", pady=2)
        self.sav_pct_lbl.pack(anchor="w", pady=2)

    def run_scenario_compare(self):
        # Build baseline from catalog
        catalog = self.catalog if isinstance(self.catalog, dict) else {}
        baseline = (catalog.get("baseline") or {}) if isinstance(catalog, dict) else {}
        bl_inputs = {
            "project": baseline.get("project", {}),
            "mix": {
                "bitumen_prop_of_mix": ((baseline.get("mix") or {}).get("bitumen_prop_of_mix")),
                "rubber_prop_of_bitumen": ((baseline.get("mix") or {}).get("rubber_prop_of_bitumen")),
                "aggregates_shares": {
                    "coarse": (((baseline.get("mix") or {}).get("aggregates") or {}).get("coarse") or {}).get("fraction_of_mix", 0.0),
                    "medium": (((baseline.get("mix") or {}).get("aggregates") or {}).get("medium") or {}).get("fraction_of_mix", 0.0),
                    "fine": (((baseline.get("mix") or {}).get("aggregates") or {}).get("fine") or {}).get("fraction_of_mix", 0.0),
                },
                "aggregates_type_ids": {
                    "coarse": (((baseline.get("mix") or {}).get("aggregates") or {}).get("coarse") or {}).get("type_id"),
                    "medium": (((baseline.get("mix") or {}).get("aggregates") or {}).get("medium") or {}).get("type_id"),
                    "fine": (((baseline.get("mix") or {}).get("aggregates") or {}).get("fine") or {}).get("type_id"),
                },
            },
            "overheads": catalog.get("overheads", {}),
        }
        # Scenario: from current GUI
        sc_inputs = self.build_mix_inputs_from_gui()

        try:
            bl = calculate_mix(bl_inputs, catalog)
            sc = calculate_mix(sc_inputs, catalog)
        except Exception as e:
            messagebox.showerror("Scenario Runner", str(e))
            return

        # Helper: cost per m2
        def area_from_proj(proj: dict) -> float:
            try:
                L = float((proj or {}).get("length_km", 0.0) or 0.0)
                W = float((proj or {}).get("width_m", 0.0) or 0.0)
                return max(1e-9, L * 1000.0 * W)
            except Exception:
                return 1.0

        def per_m2(res: dict, proj: dict) -> float:
            total = float(((res.get("costs") or {}).get("grand_total", 0.0)) or 0.0)
            return total / area_from_proj(proj)

        rows = {
            "Grand Total (EGP)": (float((bl.get("costs") or {}).get("grand_total", 0.0)), float((sc.get("costs") or {}).get("grand_total", 0.0))),
            "Materials Subtotal (EGP)": (float((bl.get("costs") or {}).get("materials_subtotal", 0.0)), float((sc.get("costs") or {}).get("materials_subtotal", 0.0))),
            "Overheads Total (EGP)": (float((bl.get("costs") or {}).get("overhead_total", 0.0)), float((sc.get("costs") or {}).get("overhead_total", 0.0))),
            "Bitumen (EGP)": (float((bl.get("costs") or {}).get("bitumen_subtotal", 0.0)), float((sc.get("costs") or {}).get("bitumen_subtotal", 0.0))),
            "Aggregates (EGP)": (float((bl.get("costs") or {}).get("aggregates_subtotal", 0.0)), float((sc.get("costs") or {}).get("aggregates_subtotal", 0.0))),
            "Rubber (EGP)": (float((bl.get("costs") or {}).get("rubber_subtotal", 0.0)), float((sc.get("costs") or {}).get("rubber_subtotal", 0.0))),
            "Cost per m² (EGP/m²)": (per_m2(bl, bl_inputs.get("project", {})), per_m2(sc, sc_inputs.get("project", {}))),
        }

        for name, (b_val, s_val) in rows.items():
            b_lbl, s_lbl, d_lbl = self.sc_rows.get(name, (None, None, None))
            if not b_lbl:
                continue
            diff = s_val - b_val
            try:
                b_lbl.configure(text=f"{b_val:,.2f}")
                s_lbl.configure(text=f"{s_val:,.2f}")
                d_lbl.configure(text=f"{diff:,.2f}")
            except Exception:
                pass

        # Savings (positive means saving if scenario < baseline)
        bl_total = rows["Grand Total (EGP)"][0]
        sc_total = rows["Grand Total (EGP)"][1]
        saving_abs = bl_total - sc_total
        saving_pct = (saving_abs / bl_total * 100.0) if bl_total > 0 else 0.0
        try:
            self.sav_abs_lbl.configure(text=f"التوفير: {saving_abs:,.0f} جنيه")
            self.sav_pct_lbl.configure(text=f"التوفير: {saving_pct:.2f}%")
        except Exception:
            pass

    # ---------------------- Presets / Standards ----------------------
    def load_standards(self) -> dict:
        try:
            with open(STANDARDS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"presets": {}, "ui": {"lock_inputs_until_preset_selected": False}}

    def apply_preset(self, code: str):
        presets = self.standards.get("presets", {})
        preset = presets.get(code)
        if not preset:
            messagebox.showwarning("Preset", f"Preset '{code}' not found")
            return
        # Fill inputs or clear for custom
        if code == "custom_template":
            for e in self.entries.values():
                e.delete(0, "end")
        else:
            defaults = preset.get("inputs_defaults", {})
            self.fill_inputs_from_defaults(defaults)
        # Set coefficients and ranges
        self.current_coeffs = preset.get("coefficients", {})
        self.current_ranges = preset.get("allowed_ranges", {})
        self.current_preset = code
        # Unlock inputs and Run button
        self.set_inputs_state("normal")
        self.run_button.configure(state="normal")

    def fill_inputs_from_defaults(self, defaults: dict):
        # Map from JSON names to GUI field keys
        mapping = {
            "road_length_km": "L",
            "road_width_m": "W",
            "layer_thickness_m": "h",
            "mixture_density_ton_per_m3": "rho_m",
            "bitumen_content_prop": "Pb",
            "plastic_of_bitumen_prop": "Pp",
            "rubber_of_bitumen_prop": "Pr",
            "temperature_C": "T",
            "annual_ESALs_million": "A",
            "aggregate_cost_per_ton": "c_agg",
            "bitumen_cost_per_ton": "c_bit",
            "plastic_cost_per_ton": "c_pl",
            "rubber_cost_per_ton": "c_rub",
            "overhead_cost": "overhead",
            "target_design_life_years": "target_design_life",
        }
        for json_key, gui_key in mapping.items():
            if json_key in defaults and gui_key in self.entries:
                self.entries[gui_key].delete(0, "end")
                self.entries[gui_key].insert(0, str(defaults[json_key]))

    def set_inputs_state(self, state: str):
        for e in self.entries.values():
            try:
                e.configure(state=state)
            except Exception:
                pass

    # ---------------------- Export ----------------------
    def build_export_inputs(self, input_values: dict, target_design_life: float) -> dict:
        # Build export structure matching standards schema keys
        return {
            "road_length_km": float(input_values.get("L", 0.0)),
            "road_width_m": float(input_values.get("W", 0.0)),
            "layer_thickness_m": float(input_values.get("h", 0.0)),
            "mixture_density_ton_per_m3": float(input_values.get("rho_m", 0.0)),
            "bitumen_content_prop": float(input_values.get("Pb", 0.0)),
            "plastic_of_bitumen_prop": float(input_values.get("Pp", 0.0)),
            "rubber_of_bitumen_prop": float(input_values.get("Pr", 0.0)),
            "temperature_C": float(input_values.get("T", 0.0)),
            "annual_ESALs_million": float(input_values.get("A", 0.0)),
            "aggregate_cost_per_ton": float(input_values.get("c_agg", 0.0)),
            "bitumen_cost_per_ton": float(input_values.get("c_bit", 0.0)),
            "plastic_cost_per_ton": float(input_values.get("c_pl", 0.0)),
            "rubber_cost_per_ton": float(input_values.get("c_rub", 0.0)),
            "overhead_cost": float(input_values.get("overhead", 0.0)),
            "target_design_life_years": float(target_design_life),
        }

    def export_run(self):
        if not self.last_results:
            messagebox.showinfo("Export", "No run to export yet.")
            return
        runs_dir = os.path.join(os.path.dirname(__file__), "runs")
        os.makedirs(runs_dir, exist_ok=True)
        # Prefer exporting catalog-based results if available
        if self.last_mix_results and exporter_export_run is not None:
            try:
                state = {
                    "inputs": self.last_mix_inputs or {},
                    "results": {
                        "quantities": (self.last_mix_results.get("quantities", {}) if isinstance(self.last_mix_results, dict) else {}),
                        "costs": (self.last_mix_results.get("costs", {}) if isinstance(self.last_mix_results, dict) else {}),
                    },
                    "warnings": list(self.last_mix_results.get("warnings", []) or []),
                    "metadata": {
                        "source": "gui",
                        "preset": self.current_preset or "unknown",
                    },
                }
                paths = exporter_export_run(state, runs_dir=runs_dir)
                messagebox.showinfo("Export", f"Saved JSON/XLSX to runs/\n{os.path.basename(paths['json'])}\n{os.path.basename(paths['xlsx'])}")
                return
            except Exception as e:
                # Fallback to JSON-only if openpyxl missing or other error
                try:
                    if exporter_export_json is not None:
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        json_path = os.path.join(runs_dir, f"{ts}_transcalc_compare.json")
                        exporter_export_json({
                            "inputs": self.last_mix_inputs or {},
                            "results": {
                                "quantities": self.last_mix_results.get("quantities", {}),
                                "costs": self.last_mix_results.get("costs", {}),
                            },
                            "warnings": list(self.last_mix_results.get("warnings", []) or []),
                            "metadata": {"source": "gui", "preset": self.current_preset or "unknown"},
                        }, json_path)
                        messagebox.showinfo("Export", f"Saved JSON to runs/{os.path.basename(json_path)}\n(Excel export requires openpyxl)")
                        return
                except Exception:
                    pass
                # continue to legacy export below
        # Legacy JSON snapshot of GUI run
        export = {
            "schema_version": self.standards.get("schema_version", "1.0.0"),
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H-%M-%S"),
            "standard_used": self.current_preset or "unknown",
            "inputs": self.last_inputs_export or {},
            "coefficients_effective": self.last_results.get("coefficients_effective", {}),
            "results": {k: v for k, v in self.last_results.items() if k not in ("warnings", "coefficients_effective")},
            "warnings": self.last_results.get("warnings", []),
        }
        fname = f"{export['timestamp']}.json"
        path = os.path.join(runs_dir, fname)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Export", f"Saved to runs/{fname}")
        except Exception as e:
            messagebox.showerror("Export", str(e))
    
    def display_results(self, results):
        """Display results in the results tab"""
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        
        # Format results
        result_str = ""
        for key, value in results.items():
            if key != "warnings":
                result_str += f"{key}: {value}\n"
        
        self.results_text.insert("1.0", result_str)
        self.results_text.configure(state="disabled")
        
    def display_warnings(self, warnings):
        """Display warnings in the warnings tab"""
        self.warnings_text.configure(state="normal")
        self.warnings_text.delete("1.0", "end")
        
        if warnings:
            warning_str = "\n".join(warnings)
        else:
            warning_str = "No warnings"
            
        self.warnings_text.insert("1.0", warning_str)
        self.warnings_text.configure(state="disabled")

    def display_warnings_inline(self, warnings):
        """Display warnings in inline warning box on Results tab"""
        if warnings:
            self.inline_warn_label.configure(text="\n".join(warnings))
        else:
            self.inline_warn_label.configure(text="No warnings")

    def update_kpis(self, results: dict):
        """Update KPI cards values"""
        life = float(results.get("design_life_years", 0.0))
        # Prefer catalog-based costs if available
        mix_res = results.get("mix_results") if isinstance(results.get("mix_results"), dict) else None
        if isinstance(mix_res, dict):
            costs = mix_res.get("costs", {}) if isinstance(mix_res.get("costs", {}), dict) else {}
            total = float(costs.get("grand_total", 0.0))
            # compute area from last_inputs_export
            try:
                L = float(self.last_inputs_export.get("road_length_km", 0.0))
                W = float(self.last_inputs_export.get("road_width_m", 0.0))
                area = max(1e-9, L * 1000.0 * W)
                per_m2 = total / area
            except Exception:
                per_m2 = 0.0
        else:
            total = float(results.get("total_cost", 0.0))
            per_m2 = float(results.get("cost_per_m2", 0.0))
        self.card_total_value.configure(text=f"{total:,.0f}")
        self.card_m2_value.configure(text=f"{per_m2:,.2f}")
        self.card_life_value.configure(text=f"{life:,.1f}")

    def update_plots(self, results: dict):
        """Update interactive charts based on results."""
        if not MATPLOT_AVAILABLE:
            return

        # Destroy previous canvas if exists
        if self.canvas is not None:
            try:
                self.canvas.get_tk_widget().destroy()
            except Exception:
                pass
            self.canvas = None

        # Prepare data (prefer catalog-based costs)
        mix_res = results.get("mix_results") if isinstance(results.get("mix_results"), dict) else None
        cost_labels = ["aggregate", "bitumen", "plastic", "rubber", "overhead"]
        if isinstance(mix_res, dict):
            mc = mix_res.get("costs", {}) if isinstance(mix_res.get("costs", {}), dict) else {}
            mapping = {
                "aggregate": float(mc.get("aggregates_subtotal", 0.0)),
                "bitumen": float(mc.get("bitumen_subtotal", 0.0)),
                "plastic": 0.0,
                "rubber": float(mc.get("rubber_subtotal", 0.0)),
                "overhead": float(mc.get("overhead_total", 0.0)),
            }
            cost_values = [mapping[k] for k in cost_labels]
        else:
            costs = results.get("costs", {})
            cost_values = [float(costs.get(k, 0.0)) for k in cost_labels]

        life_labels = ["fatigue", "rutting", "design"]
        life_values = [
            float(results.get("fatigue_life_years", 0.0)),
            float(results.get("rutting_life_years", 0.0)),
            float(results.get("design_life_years", 0.0)),
        ]

        # Create figure
        plt_style = "dark_background" if ctk.get_appearance_mode().lower() == "dark" else "default"
        with plt.style.context(plt_style):
            fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), dpi=110, constrained_layout=True)

            # Costs bar chart
            ax0 = axes[0]
            bars = ax0.bar(cost_labels, cost_values, color=[PALETTE["costs"][k] for k in cost_labels])
            ax0.set_title("Cost Breakdown (EGP)")
            ax0.tick_params(axis='x', rotation=20)
            ax0.grid(True, axis='y', alpha=0.3)
            for b in bars:
                ax0.text(b.get_x() + b.get_width()/2, b.get_height(), f"{b.get_height():.0f}", ha='center', va='bottom', fontsize=8)

            # Life bar chart
            ax1 = axes[1]
            bars2 = ax1.bar(life_labels, life_values, color=[PALETTE["life"][k] for k in life_labels])
            ax1.set_title("Life (years)")
            ax1.grid(True, axis='y', alpha=0.3)
            for b in bars2:
                ax1.text(b.get_x() + b.get_width()/2, b.get_height(), f"{b.get_height():.1f}", ha='center', va='bottom', fontsize=8)

            # Hover tooltips if available
            if MPLCURS_AVAILABLE:
                cur0 = mplcursors.cursor(bars, hover=True)
                @cur0.connect("add")
                def _(sel):
                    i = sel.index
                    sel.annotation.set(text=f"{cost_labels[i]}: {cost_values[i]:,.0f} EGP")
                    sel.annotation.get_bbox_patch().set(fc="#000000", alpha=0.7)
                cur1 = mplcursors.cursor(bars2, hover=True)
                @cur1.connect("add")
                def __(sel):
                    i = sel.index
                    sel.annotation.set(text=f"{life_labels[i]}: {life_values[i]:,.1f} years")
                    sel.annotation.get_bbox_patch().set(fc="#000000", alpha=0.7)

        # Embed in Tk
        self.canvas = FigureCanvasTkAgg(fig, master=self.plot_container)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------------------- Planner (OSM) ----------------------
    def create_planner(self, tab):
        container = ctk.CTkScrollableFrame(tab)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        hdr = ctk.CTkLabel(container, text="مخطط الطرق ومحطات الأسفلت (OSM)", font=ctk.CTkFont(size=14, weight="bold"))
        hdr.pack(anchor="w", pady=(0, 6))

        desc = ctk.CTkLabel(container, text=(
            "1) افتح صفحة الرسم وارسم المسار واحفظه GeoJSON.\n"
            "2) استورد ملف GeoJSON.\n"
            "3) شغّل التحليل لجلب المحطات والمحاجر ومراكز تدوير المطاط وترتيبها."
        ))
        desc.pack(anchor="w")

        # Actions row
        actions = ctk.CTkFrame(container)
        actions.pack(fill="x", pady=8)
        ctk.CTkButton(actions, text="فتح صفحة الرسم", command=self.open_map_draw_html).pack(side="left", padx=6)
        ctk.CTkButton(actions, text="استيراد GeoJSON", command=self.import_planner_geojson).pack(side="left", padx=6)
        self.btn_run_planner = ctk.CTkButton(actions, text="تشغيل التحليل", command=self.run_planner_analysis)
        self.btn_run_planner.pack(side="left", padx=6)

        # Selected file label
        self.pl_selected_file_lbl = ctk.CTkLabel(container, text="لم يتم اختيار ملف GeoJSON بعد")
        self.pl_selected_file_lbl.pack(fill="x", pady=(0, 8))

        # Segment controls
        seg_frame = ctk.CTkFrame(container)
        seg_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(seg_frame, text="مقطع المسار (اختياري)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=6, pady=(6, 0))
        row1 = ctk.CTkFrame(seg_frame); row1.pack(fill="x", padx=6, pady=4)
        ctk.CTkLabel(row1, text="طول المقطع (كم)", width=140).pack(side="left")
        self.pl_seg_len_km_var = ctk.StringVar(value="")
        ctk.CTkEntry(row1, textvariable=self.pl_seg_len_km_var).pack(side="left", padx=8)
        ctk.CTkLabel(row1, text="موضع النقطة:").pack(side="left", padx=(16, 4))
        self.pl_anchor_var = ctk.StringVar(value="وسط")
        self.pl_anchor_menu = ctk.CTkOptionMenu(row1, values=["أول", "وسط", "آخر"], variable=self.pl_anchor_var)
        self.pl_anchor_menu.pack(side="left")
        self.pl_bidir_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(row1, text="تحليل في اتجاهين", variable=self.pl_bidir_var).pack(side="left", padx=12)

        # Weights
        self.pl_weight_vars = {}
        weights_frame = ctk.CTkFrame(container)
        weights_frame.pack(fill="x", pady=6)
        ctk.CTkLabel(weights_frame, text="الأوزان (اختياري)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=6, pady=(6, 0))
        grid = ctk.CTkFrame(weights_frame)
        grid.pack(fill="x", padx=6, pady=6)
        labels = [
            ("قرب الطريق", "road_proximity"),
            ("قرب منتصف المسار", "midpoint_preference"),
            ("قرب المحاجر", "quarry_proximity"),
            ("قرب تدوير المطاط", "rubber_proximity"),
            ("استخدام/نوع الأرض (OSM)", "landuse_preference"),
            ("قرب الطرق السريعة", "highway_proximity"),
            ("قرب مصانع خرسانة جاهزة", "ready_mix_proximity"),
            ("قرب مصادر بيتومين", "bitumen_source_proximity"),
        ]
        # Defaults
        try:
            defaults = dict(PL_DEFAULT_WEIGHTS) if PLANNER_AVAILABLE else {"road_proximity":5,"midpoint_preference":4,"quarry_proximity":2,"rubber_proximity":1,"landuse_preference":3}
        except Exception:
            defaults = {"road_proximity":5,"midpoint_preference":4,"quarry_proximity":2,"rubber_proximity":1,"landuse_preference":3}
        for i, (ar, key) in enumerate(labels):
            row = ctk.CTkFrame(grid)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=ar, width=180).pack(side="left")
            var = ctk.StringVar(value=str(defaults.get(key, 1.0)))
            ent = ctk.CTkEntry(row, textvariable=var)
            ent.pack(side="left", padx=8, fill="x", expand=True)
            self.pl_weight_vars[key] = var

        # Results area
        self.pl_results_text = ctk.CTkTextbox(container, wrap="word", height=200)
        self.pl_results_text.pack(fill="both", expand=True, pady=8)
        self.pl_results_text.insert("1.0", "النتائج ستظهر هنا بعد تشغيل التحليل...")
        self.pl_results_text.configure(state="disabled")

        # Open map button
        self.pl_open_map_btn = ctk.CTkButton(container, text="فتح الخريطة الناتجة", command=self.open_planner_map)
        self.pl_open_map_btn.pack(pady=(0, 4))
        self.pl_open_map_btn.configure(state="disabled")

        # Bidirectional preview/adopt buttons
        self.pl_open_map_fwd_btn = ctk.CTkButton(container, text="فتح معاينة الاتجاه الأمامي", command=self.open_planner_map_fwd)
        self.pl_open_map_rev_btn = ctk.CTkButton(container, text="فتح معاينة الاتجاه العكسي", command=self.open_planner_map_rev)
        self.pl_adopt_fwd_btn = ctk.CTkButton(container, text="اعتماد الاتجاه الأمامي", command=self.adopt_forward_analysis)
        self.pl_adopt_rev_btn = ctk.CTkButton(container, text="اعتماد الاتجاه العكسي", command=self.adopt_reverse_analysis)
        for b in (self.pl_open_map_fwd_btn, self.pl_open_map_rev_btn, self.pl_adopt_fwd_btn, self.pl_adopt_rev_btn):
            b.pack(pady=(0, 4))
            b.configure(state="disabled")

        # Export planner report button
        self.pl_export_btn = ctk.CTkButton(container, text="تصدير تقرير المخطط (JSON/CSV)", command=self.export_planner_report)
        self.pl_export_btn.pack(pady=(0, 4))
        self.pl_export_btn.configure(state="disabled")

        # State
        self.pl_geojson_file = None
        self.pl_last_analysis = None
        self.pl_bidir_results = None  # {"forward": dict, "reverse": dict}

        # Disable if planner missing
        if not PLANNER_AVAILABLE:
            try:
                self.btn_run_planner.configure(state="disabled")
                self.pl_results_text.configure(state="normal")
                self.pl_results_text.delete("1.0", "end")
                self.pl_results_text.insert("1.0", "المكوّن planner غير متاح. ثبّت المتطلبات: requests, folium.")
                self.pl_results_text.configure(state="disabled")
            except Exception:
                pass

    def open_map_draw_html(self):
        try:
            html_path = os.path.join(self.app_dir(), "map_draw.html")
            if not os.path.exists(html_path):
                messagebox.showwarning("Planner", "لم يتم العثور على map_draw.html")
                return
            webbrowser.open_new_tab(Path(html_path).as_uri())
        except Exception as e:
            messagebox.showerror("Planner", str(e))

    def import_planner_geojson(self):
        try:
            fpath = filedialog.askopenfilename(title="اختر ملف GeoJSON للمسار",
                                               filetypes=[("GeoJSON","*.geojson"), ("JSON","*.json"), ("All","*.*")])
        except Exception:
            fpath = ""
        if not fpath:
            return
        self.pl_geojson_file = fpath
        try:
            self.pl_selected_file_lbl.configure(text=f"المسار المختار: {os.path.basename(fpath)}")
        except Exception:
            pass

    def run_planner_analysis(self):
        if not PLANNER_AVAILABLE:
            messagebox.showwarning("Planner", "المكوّن planner غير متاح")
            return
        if not self.pl_geojson_file:
            messagebox.showinfo("Planner", "من فضلك استورد ملف GeoJSON أولاً")
            return
        # Read weights
        weights = {}
        for k, var in (self.pl_weight_vars or {}).items():
            try:
                weights[k] = float(var.get())
            except Exception:
                # fallback to default
                try:
                    weights[k] = float(PL_DEFAULT_WEIGHTS.get(k, 1.0))
                except Exception:
                    weights[k] = 1.0
        # UI state
        try:
            self.btn_run_planner.configure(state="disabled", text="...جاري التحليل")
        except Exception:
            pass
        try:
            path_pts = planner_load_geojson_path(self.pl_geojson_file)
            # Segment options
            seg_txt = (self.pl_seg_len_km_var.get() or "").strip()
            seg_len_km = float(seg_txt) if seg_txt else 0.0
            anchor_map = {"أول":"start", "وسط":"mid", "آخر":"end"}
            anchor_choice = anchor_map.get(self.pl_anchor_var.get(), "mid")
            bidir = bool(self.pl_bidir_var.get())

            # Reset UI controls
            for b in (self.pl_open_map_fwd_btn, self.pl_open_map_rev_btn, self.pl_adopt_fwd_btn, self.pl_adopt_rev_btn):
                b.configure(state="disabled")
            self.pl_open_map_btn.configure(state="disabled")
            self.pl_export_btn.configure(state="disabled")
            self.pl_bidir_results = None
            self.pl_last_analysis = None

            if seg_len_km > 0 and bidir:
                # forward and reverse segments
                seg_fwd = planner_slice_path_segment(path_pts, seg_len_km, anchor_choice, "forward")
                seg_rev = planner_slice_path_segment(path_pts, seg_len_km, anchor_choice, "reverse")
                res_fwd = planner_analyze_path(seg_fwd, top_k=5, weights=weights)
                res_rev = planner_analyze_path(seg_rev, top_k=5, weights=weights)
                self.pl_bidir_results = {"forward": res_fwd, "reverse": res_rev}

                # Render summary for both
                lines = ["— النتائج (اتجاهان) —"]
                def _fmt_fb_list(items, label):
                    if not items:
                        return [f"  لا يوجد {label} ضمن 50 كم"]
                    out = [f"  {label} ({len(items)}):"]
                    for i, it in enumerate(items[:5], 1):
                        dkm = float((it or {}).get('distance_to_path_m', 0.0)) / 1000.0
                        nm = (it or {}).get('name', label)
                        out.append(f"    {i}. {nm} — {dkm:.1f} كم")
                    return out
                def summarize(tag, res):
                    lines.append(f"[{tag}] Existing: {len(res.get('existing', []))} | Proposed: {len(res.get('proposed', []))}")
                    lines.append(f"[{tag}] Highways: {len(res.get('highways', []))} | ReadyMix: {len(res.get('ready_mix', []))} | Bitumen: {len(res.get('bitumen_sources', []))}")
                    # Fallback sections
                    lines.extend(_fmt_fb_list(res.get('fallback_asphalt', []), "محطات أسفلت (احتياط)"))
                    lines.extend(_fmt_fb_list(res.get('fallback_waste', []), "مواقع مخلفات/نفايات (احتياط)"))
                    lines.extend(_fmt_fb_list(res.get('fallback_rubber_recycling', []), "مصانع تدوير مطاط (احتياط)"))
                    lines.extend(_fmt_fb_list(res.get('fallback_rubber_production', []), "مصانع إنتاج مطاط (احتياط)"))
                    mp = res.get('map_path')
                    if mp:
                        lines.append(f"[{tag}] خريطة: {os.path.basename(mp)}")
                    lines.append("")
                summarize("أمامي", res_fwd)
                summarize("عكسي", res_rev)

                # Enable preview/adopt buttons
                for b in (self.pl_open_map_fwd_btn, self.pl_open_map_rev_btn, self.pl_adopt_fwd_btn, self.pl_adopt_rev_btn):
                    b.configure(state="normal")

                # Update UI
                self.pl_results_text.configure(state="normal")
                self.pl_results_text.delete("1.0", "end")
                self.pl_results_text.insert("1.0", "\n".join(lines))
                self.pl_results_text.configure(state="disabled")
            else:
                # Single analysis (full path or single segment)
                use_path = path_pts
                if seg_len_km > 0:
                    use_path = planner_slice_path_segment(path_pts, seg_len_km, anchor_choice, "forward")
                res = planner_analyze_path(use_path, top_k=5, weights=weights)
                self.pl_last_analysis = res

                # Render summary
                lines = []
                lines.append("— النتائج —")
                lines.append(f"Existing asphalt plants (top): {len(res.get('existing', []))}")
                for i, a in enumerate(res.get("existing", []), 1):
                    sc_all = (a.get("score") or {})
                    sc = sc_all.get("total_score", 0.0)
                    scn = sc_all.get("total_score_norm", 0.0)
                    lines.append(f"  {i}. {a.get('name','Asphalt')} | score={sc:.2f} (norm {scn:.2f}) | ({a.get('lat'):.4f}, {a.get('lon'):.4f})")
                lines.append("")
                lines.append(f"Proposed sites: {len(res.get('proposed', []))}")
                for i, p in enumerate(res.get("proposed", []), 1):
                    sc_all = (p.get("score") or {})
                    sc = sc_all.get("total_score", 0.0)
                    scn = sc_all.get("total_score_norm", 0.0)
                    lines.append(f"  {i}. {p.get('name','Proposed')} | score={sc:.2f} (norm {scn:.2f}) | ({p.get('lat'):.4f}, {p.get('lon'):.4f})")
                lines.append("")
                lines.append(f"Quarries found: {len(res.get('quarries', []))}")
                lines.append(f"Rubber recycling found: {len(res.get('rubbers', []))}")
                lines.append(f"Highways (major) found: {len(res.get('highways', []))}")
                lines.append(f"Ready-mix plants found: {len(res.get('ready_mix', []))}")
                lines.append(f"Bitumen sources found: {len(res.get('bitumen_sources', []))}")
                # Fallback lists with distances (top 5)
                def _fmt_fb_list(items, label):
                    if not items:
                        return [f"  لا يوجد {label} ضمن 50 كم"]
                    out = [f"  {label} ({len(items)}):"]
                    for i, it in enumerate(items[:5], 1):
                        dkm = float((it or {}).get('distance_to_path_m', 0.0)) / 1000.0
                        nm = (it or {}).get('name', label)
                        out.append(f"    {i}. {nm} — {dkm:.1f} كم")
                    return out
                lines.append("")
                lines.append("Fallback facilities within 50 km:")
                lines.extend(_fmt_fb_list(res.get('fallback_asphalt', []), "محطات أسفلت (احتياط)"))
                lines.extend(_fmt_fb_list(res.get('fallback_waste', []), "مواقع مخلفات/نفايات (احتياط)"))
                lines.extend(_fmt_fb_list(res.get('fallback_rubber_recycling', []), "مصانع تدوير مطاط (احتياط)"))
                lines.extend(_fmt_fb_list(res.get('fallback_rubber_production', []), "مصانع إنتاج مطاط (احتياط)"))
                mp = res.get("map_path")
                if mp and os.path.exists(mp):
                    lines.append("")
                    lines.append(f"خريطة تفاعلية تم حفظها: {os.path.basename(mp)} (runs/)")
                    try:
                        self.pl_open_map_btn.configure(state="normal")
                    except Exception:
                        pass
                # enable export only when we have adopted single analysis
                if exporter_export_planner is not None and isinstance(self.pl_last_analysis, dict):
                    self.pl_export_btn.configure(state="normal")

                # Update UI
                self.pl_results_text.configure(state="normal")
                self.pl_results_text.delete("1.0", "end")
                self.pl_results_text.insert("1.0", "\n".join(lines))
                self.pl_results_text.configure(state="disabled")
        except Exception as e:
            messagebox.showerror("Planner", str(e))
        finally:
            try:
                self.btn_run_planner.configure(state="normal", text="تشغيل التحليل")
            except Exception:
                pass

    def open_planner_map(self):
        try:
            if self.pl_last_analysis and isinstance(self.pl_last_analysis, dict):
                mp = self.pl_last_analysis.get("map_path")
                if mp and os.path.exists(mp):
                    webbrowser.open_new_tab(Path(mp).as_uri())
                    return
            messagebox.showinfo("Planner", "لا توجد خريطة صالحة للعرض")
        except Exception as e:
            messagebox.showerror("Planner", str(e))

    def open_planner_map_fwd(self):
        try:
            res = (self.pl_bidir_results or {}).get("forward") if isinstance(self.pl_bidir_results, dict) else None
            mp = (res or {}).get("map_path")
            if mp and os.path.exists(mp):
                webbrowser.open_new_tab(Path(mp).as_uri())
            else:
                messagebox.showinfo("Planner", "لا توجد خريطة للاتجاه الأمامي")
        except Exception as e:
            messagebox.showerror("Planner", str(e))

    def open_planner_map_rev(self):
        try:
            res = (self.pl_bidir_results or {}).get("reverse") if isinstance(self.pl_bidir_results, dict) else None
            mp = (res or {}).get("map_path")
            if mp and os.path.exists(mp):
                webbrowser.open_new_tab(Path(mp).as_uri())
            else:
                messagebox.showinfo("Planner", "لا توجد خريطة للاتجاه العكسي")
        except Exception as e:
            messagebox.showerror("Planner", str(e))

    def adopt_forward_analysis(self):
        try:
            res = (self.pl_bidir_results or {}).get("forward") if isinstance(self.pl_bidir_results, dict) else None
            if not isinstance(res, dict):
                messagebox.showinfo("Planner", "لا توجد نتائج لاعتماد الاتجاه الأمامي")
                return
            self.pl_last_analysis = res
            if exporter_export_planner is not None:
                self.pl_export_btn.configure(state="normal")
            messagebox.showinfo("Planner", "تم اعتماد الاتجاه الأمامي للتصدير")
        except Exception as e:
            messagebox.showerror("Planner", str(e))

    def adopt_reverse_analysis(self):
        try:
            res = (self.pl_bidir_results or {}).get("reverse") if isinstance(self.pl_bidir_results, dict) else None
            if not isinstance(res, dict):
                messagebox.showinfo("Planner", "لا توجد نتائج لاعتماد الاتجاه العكسي")
                return
            self.pl_last_analysis = res
            if exporter_export_planner is not None:
                self.pl_export_btn.configure(state="normal")
            messagebox.showinfo("Planner", "تم اعتماد الاتجاه العكسي للتصدير")
        except Exception as e:
            messagebox.showerror("Planner", str(e))

    def export_planner_report(self):
        try:
            if exporter_export_planner is None:
                messagebox.showwarning("Planner", "وحدة التصدير غير متاحة")
                return
            if not (self.pl_last_analysis and isinstance(self.pl_last_analysis, dict)):
                messagebox.showinfo("Planner", "لا توجد نتائج لتصديرها. شغّل التحليل أولاً.")
                return
            paths = exporter_export_planner(self.pl_last_analysis, runs_dir=os.path.join(self.app_dir(), "runs"))
            msg = ["تم تصدير تقرير المخطط:"]
            for k, p in (paths or {}).items():
                msg.append(f"- {k}: {os.path.basename(p)}")
            messagebox.showinfo("Planner", "\n".join(msg))
        except Exception as e:
            messagebox.showerror("Planner", str(e))

if __name__ == "__main__":
    app = PavementApp()
    app.mainloop()
