"""User-visible opt-in setup for GRN cloud recognition."""

import tkinter as tk
import sqlite3
from tkinter import ttk

from grn_cloud_ocr import cloud_settings, load_credential, save_credential, usage_today, validate_endpoint, OCR_SPACE_ENDPOINT, is_ocr_space


class GRNOCRSettings:
    def __init__(self, parent, store):
        self.store = store
        config = cloud_settings(store)
        self.window = tk.Toplevel(parent)
        self.window.title('GRN OCR Settings')
        self.window.transient(parent)
        self.window.resizable(False, False)
        frame = ttk.Frame(self.window, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Local OCR first; OCR.space for difficult photos', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='OCR.space receives the header crop, or the photo if the header cannot be located.\n'
                  'Enter your OCR.space API key (the website login is not an API key). Service quotas apply.\n'
                  'Engine 2 reads word positions. Uploads are limited to 1 MB for free-plan compatibility.\n'
                  'The API key is stored in Windows Credential Manager.', wraplength=560).pack(anchor='w', pady=10)
        self.enabled = tk.BooleanVar(value=config['enabled'] if is_ocr_space(config['endpoint']) else False)
        ttk.Checkbutton(frame, text='Automatically upload difficult photos to OCR.space', variable=self.enabled).pack(anchor='w', pady=6)
        self.endpoint = tk.StringVar(value=config['endpoint'] if is_ocr_space(config['endpoint']) else OCR_SPACE_ENDPOINT)
        self.key = tk.StringVar()
        self.limit = tk.StringVar(value=str(config['daily_limit']) if config['daily_limit'] else '')
        for text, variable, hidden in [('OCR.space API endpoint (Free or your PRO endpoint)', self.endpoint, False),
                                       ('OCR.space API key (blank keeps the saved key)', self.key, True),
                                       ('Daily upload limit (positive whole number)', self.limit, False)]:
            ttk.Label(frame, text=text).pack(anchor='w', pady=(8, 2))
            ttk.Entry(frame, textvariable=variable, width=70, show='*' if hidden else '').pack(fill='x')
        ttk.Label(frame, text=f'Uploads reserved today: {usage_today(store)}. The day follows this PC’s local date.\n'
                  'Uncertain uploads count toward the limit. Retry Cloud uploads them again and may incur another charge.\n'
                  'OCR.space returns results in one request. Lost responses cannot be resumed; retry sends another upload.',
                  wraplength=560).pack(anchor='w', pady=10)
        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status, wraplength=560).pack(anchor='w', pady=6)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='Save Settings', command=self.save).pack(side='right')
        ttk.Button(buttons, text='Close', command=self.window.destroy).pack(side='right', padx=8)

    def save(self):
        try:
            endpoint = validate_endpoint(self.endpoint.get()) if self.endpoint.get().strip() else ''
            if endpoint and not is_ocr_space(endpoint):
                raise ValueError('Enter your OCR.space /parse/image API endpoint.')
            limit = int(self.limit.get()) if self.limit.get().strip() else 0
            if limit < 0:
                raise ValueError('The daily upload limit cannot be negative.')
            if self.enabled.get() and (not endpoint or limit < 1):
                raise ValueError('Enter the resource endpoint and a positive daily upload limit before enabling uploads.')
            if self.key.get().strip():
                if not endpoint:
                    raise ValueError('Enter the OCR.space API endpoint before saving its key.')
                save_credential(endpoint, self.key.get())
                self.key.set('')
            if self.enabled.get() and not load_credential(endpoint):
                raise ValueError('Save your OCR.space API key before enabling uploads.')
            self.store.set_settings(grn_cloud_ocr={'provider': 'ocr_space', 'enabled': self.enabled.get(), 'endpoint': endpoint, 'daily_limit': limit})
            self.status.set('Saved. New difficult photos use this setting. Use Retry Extraction for an existing photo.')
        except (ValueError, RuntimeError, OSError, ImportError, sqlite3.Error) as exc:
            self.status.set(str(exc))
