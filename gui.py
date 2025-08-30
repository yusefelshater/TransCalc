"""
GUI for Pavement Performance Model using customtkinter
with interactive charts (matplotlib) in the Results tab.
"""
import customtkinter as ctk
from tkinter import messagebox, filedialog
from model import run_model
import json
import os
import sys
import shutil
import subprocess
from datetime import datetime

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
        
        # Results tab
        self.results_tab = self.tabs.add("Results")
        self.create_results(self.results_tab)
        
        # Warnings tab
        self.warnings_tab = self.tabs.add("Warnings")
        self.warnings_text = ctk.CTkTextbox(self.warnings_tab, wrap="word")
        self.warnings_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.warnings_text.configure(state="disabled")
        
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

        # Lock inputs and Run button until preset selected (if configured)
        if self.ui_lock_inputs:
            self.set_inputs_state("disabled")
            self.run_button.configure(state="disabled")
    
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
        
        # Run the model
        try:
            results = run_model(
                **input_values,
                target_design_life=target_design_life,
                coeffs=self.current_coeffs or {},
                allowed_ranges=self.current_ranges,
            )
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
        export = {
            "schema_version": self.standards.get("schema_version", "1.0.0"),
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H-%M-%S"),
            "standard_used": self.current_preset or "unknown",
            "inputs": self.last_inputs_export or {},
            "coefficients_effective": self.last_results.get("coefficients_effective", {}),
            "results": {k: v for k, v in self.last_results.items() if k not in ("warnings", "coefficients_effective")},
            "warnings": self.last_results.get("warnings", []),
        }
        # Ensure runs directory
        runs_dir = os.path.join(os.path.dirname(__file__), "runs")
        os.makedirs(runs_dir, exist_ok=True)
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
        total = float(results.get("total_cost", 0.0))
        per_m2 = float(results.get("cost_per_m2", 0.0))
        life = float(results.get("design_life_years", 0.0))
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

        # Prepare data
        costs = results.get("costs", {})
        cost_labels = ["aggregate", "bitumen", "plastic", "rubber", "overhead"]
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

if __name__ == "__main__":
    app = PavementApp()
    app.mainloop()
