#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os

# Ensure the parent directory is in the path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from smutscrape.cli import get_site_manager, load_configuration, get_session_manager
from smutscrape.core import process_list_page, construct_url

class SmutscrapeGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Smutscrape GUI")
        self.root.geometry("600x500")
        
        # Site Selection
        tk.Label(root, text="Select Site:").pack(pady=5)
        self.site_manager = get_site_manager()
        self.sites = self.site_manager.sites
        self.site_names = sorted([s.name for s in self.sites.values()])
        self.site_var = tk.StringVar()
        self.site_combo = ttk.Combobox(root, textvariable=self.site_var, values=self.site_names)
        self.site_combo.pack(pady=5)
        self.site_combo.bind("<<ComboboxSelected>>", self.update_modes)
        
        # Mode Selection
        tk.Label(root, text="Select Mode:").pack(pady=5)
        self.mode_var = tk.StringVar()
        self.mode_combo = ttk.Combobox(root, textvariable=self.mode_var)
        self.mode_combo.pack(pady=5)
        
        # Query/Identifier
        tk.Label(root, text="Query / Identifier:").pack(pady=5)
        self.query_entry = tk.Entry(root, width=50)
        self.query_entry.pack(pady=5)
        
        # Filters
        filter_frame = tk.LabelFrame(root, text="Filters")
        filter_frame.pack(pady=10, padx=10, fill="x")
        
        tk.Label(filter_frame, text="After Date (YYYY-MM-DD):").grid(row=0, column=0, padx=5, pady=5)
        self.after_entry = tk.Entry(filter_frame)
        self.after_entry.grid(row=0, column=1, padx=5, pady=5)
        
        tk.Label(filter_frame, text="Min Duration (min):").grid(row=1, column=0, padx=5, pady=5)
        self.min_dur_entry = tk.Entry(filter_frame)
        self.min_dur_entry.grid(row=1, column=1, padx=5, pady=5)
        
        # Options
        self.overwrite_var = tk.BooleanVar()
        tk.Checkbutton(root, text="Overwrite existing files", variable=self.overwrite_var).pack()
        
        # Run Button
        self.run_button = tk.Button(root, text="Start Scraping", command=self.start_scraping, bg="green", fg="white")
        self.run_button.pack(pady=20)
        
        # Status
        self.status_label = tk.Label(root, text="Ready", fg="blue")
        self.status_label.pack(pady=5)

    def update_modes(self, event):
        site_name = self.site_var.get()
        site_config = next(s for s in self.sites.values() if s.name == site_name)
        modes = [m for m in site_config.modes.keys() if m != 'video']
        self.mode_combo['values'] = modes
        if modes: self.mode_combo.current(0)

    def start_scraping(self):
        site_name = self.site_var.get()
        mode = self.mode_var.get()
        query = self.query_entry.get()
        
        if not site_name or not mode or not query:
            messagebox.showwarning("Input Error", "Please select site, mode and enter a query.")
            return
            
        self.run_button.config(state="disabled")
        self.status_label.config(text="Scraping in progress... check terminal for logs.")
        
        # Run in a separate thread to keep GUI responsive
        thread = threading.Thread(target=self.run_task, args=(site_name, mode, query))
        thread.start()

    def run_task(self, site_name, mode, query):
        try:
            site_config = next(s for s in self.sites.values() if s.name == site_name)
            general_config = load_configuration('general')
            state_set = get_session_manager().processed_urls
            
            mode_config = site_config.modes[mode]
            url = construct_url(site_config.base_url, mode_config['url_pattern'], site_config, mode=mode, **{mode: query})
            
            # This is a simplified call to core logic
            process_list_page(
                url, site_config, general_config, 
                mode=mode, identifier=query, 
                overwrite=self.overwrite_var.get(),
                state_set=state_set,
                after_date=self.after_entry.get(),
                min_duration=self.min_dur_entry.get()
            )
            
            self.root.after(0, lambda: self.status_label.config(text="Finished!"))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self.status_label.config(text="Error occurred."))
        finally:
            self.root.after(0, lambda: self.run_button.config(state="normal"))

def launch_gui():
    root = tk.Tk()
    app = SmutscrapeGUI(root)
    root.mainloop()

if __name__ == "__main__":
    launch_gui()
