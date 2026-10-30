"""Regression checks using synthetic spreadsheets and real Tk widgets, without mocks."""

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

import pandas as pd

from reconciliation_tool import ReconciliationApp


class ReconciliationTransformTests(unittest.TestCase):
    def setUp(self):
        self.app = ReconciliationApp.__new__(ReconciliationApp)
        self.app.log_messages = []

    def test_split_uses_current_rows_preserves_index_and_unlimited_final_part(self):
        tail = "x" * 150
        source = pd.DataFrame(
            {'Raw': ['AB001', None, 'C', 'DD' + tail], 'Qty': [1, 2, 3, 4]},
            index=[10, 20, 30, 40],
        )
        result = self.app.apply_text_to_columns(source, 'Raw', [2, 100], 'History')
        self.assertEqual(['AB', '', 'C', 'DD'], result['Raw_part_1'].tolist())
        self.assertEqual(['001', '', '', tail], result['Raw_part_2'].tolist())
        self.assertEqual([10, 20, 30, 40], result.index.tolist())
        self.assertEqual(['Raw_part_1', 'Raw_part_2', 'Qty'], result.columns.tolist())
        self.assertEqual(['Raw', 'Qty'], source.columns.tolist())

    def test_empty_split_keeps_expected_columns(self):
        result = self.app.apply_text_to_columns(
            pd.DataFrame(columns=['Raw', 'Qty']), 'Raw', [2, 100], 'Plan'
        )
        self.assertEqual(['Raw_part_1', 'Raw_part_2', 'Qty'], result.columns.tolist())
        self.assertTrue(result.empty)

    def test_split_accepts_nullable_numeric_columns_with_blanks(self):
        source = pd.DataFrame({'Raw': pd.Series([12345, None, 67890], dtype='Int64')})
        result = self.app.apply_text_to_columns(source, 'Raw', [2, 100], 'History')
        self.assertEqual(['12', '', '67'], result['Raw_part_1'].tolist())
        self.assertEqual(['345', '', '890'], result['Raw_part_2'].tolist())


class ReconciliationDialogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.folder = Path(self.temp_dir.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.app = ReconciliationApp.__new__(ReconciliationApp)
        self.app.SETTINGS_FILE = str(self.folder / 'settings.json')
        self.app.__init__(self.root, standalone=False)
        self.app.queued_job_id.set('')
        self.app.auto_open_file.set(False)
        self.app.archive_var.set(False)
        self.app.output_folder.set(str(self.folder))

    def widgets(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def button(self, parent, text):
        return next(
            widget for widget in self.widgets(parent)
            if isinstance(widget, ttk.Button) and widget.cget('text') == text
        )

    def interact_with_dialog(self, action, callback):
        failures = []

        def interact():
            dialog = next(widget for widget in self.root.winfo_children()
                          if isinstance(widget, tk.Toplevel))
            try:
                callback(dialog)
            except Exception as error:
                failures.append(error)
                dialog.destroy()

        self.root.after(0, interact)
        action()
        if failures:
            raise failures[0]

    def load_frame(self, file_type, frame):
        path = self.folder / f'{file_type}.xlsx'
        frame.to_excel(path, index=False)
        getattr(self.app, f'{file_type}_file_path').set(str(path))
        columns = self.app.load_column_names(
            str(path), getattr(self.app, f'{file_type}_load_id_combo'),
            getattr(self.app, f'{file_type}_qty_combo'),
            getattr(self.app, f'{file_type}_load_id_col'),
            getattr(self.app, f'{file_type}_qty_col'),
            getattr(self.app, f'{file_type}_split_combo'),
        )
        self.assertEqual(frame.columns.tolist(), columns)
        getattr(self.app, f'{file_type}_qty_col').set('Qty')
        self.app.populate_preview(file_type)
        return path

    def split(self, file_type, column):
        getattr(self.app, f'{file_type}_split_enabled').set(True)
        getattr(self.app, f'toggle_{file_type}_split')()
        getattr(self.app, f'{file_type}_split_column').set(column)

        def configure(dialog):
            self.button(dialog, 'Auto-Detect').invoke()
            self.button(dialog, 'Apply Split').invoke()

        self.interact_with_dialog(lambda: self.app.configure_split(file_type), configure)

    def concatenate(self, file_type, columns, new_name, separator='-', drop=False):
        def configure(dialog):
            lists = [widget for widget in self.widgets(dialog) if isinstance(widget, tk.Listbox)]
            available = lists[0]
            for column in columns:
                available.selection_clear(0, tk.END)
                available.selection_set(available.get(0, tk.END).index(column))
                self.button(dialog, 'Add ▶').invoke()
            name_entry = next(widget for widget in self.widgets(dialog)
                              if isinstance(widget, ttk.Entry) and not isinstance(widget, ttk.Combobox))
            name_entry.delete(0, tk.END)
            name_entry.insert(0, new_name)
            combo = next(widget for widget in self.widgets(dialog) if isinstance(widget, ttk.Combobox))
            combo.set(separator)
            if drop:
                next(widget for widget in self.widgets(dialog)
                     if isinstance(widget, ttk.Checkbutton)).invoke()
            self.button(dialog, 'Apply Concatenate').invoke()

        self.interact_with_dialog(lambda: self.app.open_concatenate_dialog(file_type), configure)

    def dismiss_messages(self, action):
        """Close actual Tk message boxes so the real processing path can finish."""
        def dismiss():
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes

                @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                def close_test_message(window, _data):
                    class_name = ctypes.create_unicode_buffer(256)
                    ctypes.windll.user32.GetClassNameW(window, class_name, len(class_name))
                    if class_name.value == '#32770':
                        ctypes.windll.user32.PostMessageW(ctypes.c_void_p(window), 0x0010, 0, 0)
                    return True

                ctypes.windll.user32.EnumThreadWindows(
                    ctypes.windll.kernel32.GetCurrentThreadId(), close_test_message, 0
                )
            elif self.root.tk.call('winfo', 'exists', '.__tk__messagebox'):
                self.root.tk.call('destroy', '.__tk__messagebox')
            self.dismiss_id = self.root.after(20, dismiss)

        self.dismiss_id = self.root.after(20, dismiss)
        try:
            action()
        finally:
            self.root.after_cancel(self.dismiss_id)

    def test_split_then_concatenate_matches_preview_and_writes_report(self):
        source = pd.DataFrame({'Raw': ['AB  001  ZZ', 'CD  002  YY'], 'Qty': [5, 7]})
        for file_type, drop in (('history', False), ('plan', True)):
            self.load_frame(file_type, source)
            self.split(file_type, 'Raw')
            self.concatenate(file_type, ['Raw_part_2', 'Raw_part_1'], 'Key', drop=drop)
            self.assertEqual('', getattr(self.app, f'{file_type}_split_column').get())
            preview = getattr(self.app, f'{file_type}_df_loaded')
            self.assertEqual(['001-AB', '002-CD'], preview['Key'].tolist())
            replay = self.app.apply_column_transformations(source, file_type)
            pd.testing.assert_frame_equal(preview, replay)

        # Blank split selectors must not block Run before file validation.
        history_path = self.app.history_file_path.get()
        self.app.history_file_path.set(str(self.folder / 'missing.xlsx'))
        self.dismiss_messages(self.app.run_reconciliation)
        self.assertIn('History file:', self.app.error_message.get())
        self.app.history_file_path.set(history_path)

        self.app.error_message.set('')
        self.dismiss_messages(self.app.process_reconciliation)
        self.assertEqual('', self.app.error_message.get())
        report = Path(self.app.last_output_file)
        self.assertTrue(report.is_file())
        variance = pd.read_excel(report, sheet_name='variance')
        self.assertEqual(['001-AB', '002-CD'], variance['Load ID'].tolist())
        self.assertEqual(['MATCH', 'MATCH'], variance['Status'].tolist())
        summary = pd.read_excel(report, sheet_name='Summary').set_index('Metric')['Value']
        self.assertIn('Column: Raw, Widths:', summary['History Text-to-Columns'])
        self.assertIn('Column: Raw, Widths:', summary['Plan Text-to-Columns'])

    def test_concatenate_split_concatenate_and_multiple_splits_replay_in_order(self):
        source = pd.DataFrame({
            'Prefix': ['AB', 'CD'], 'Number': ['N01', 'N02'], 'Suffix': ['ZZ', 'YY'], 'Qty': [5, 7]
        })
        for file_type in ('history', 'plan'):
            with self.subTest(file_type=file_type):
                self.load_frame(file_type, source)
                self.concatenate(file_type, ['Prefix', 'Number', 'Suffix'], 'Raw', separator='  ', drop=True)
                self.split(file_type, 'Raw')
                self.concatenate(file_type, ['Raw_part_2', 'Raw_part_1', 'Raw_part_3'], 'Combined', separator='  ', drop=True)
                self.split(file_type, 'Combined')
                preview = getattr(self.app, f'{file_type}_df_loaded')
                replay = self.app.apply_column_transformations(source, file_type)
                pd.testing.assert_frame_equal(preview, replay)
                self.assertEqual(['N01', 'N02'], replay['Combined_part_1'].tolist())
                changed = source.iloc[:1].copy()
                changed['Number'] = 'N99'
                changed.index = [42]
                replay = self.app.apply_column_transformations(changed, file_type)
                self.assertEqual(['N99'], replay['Combined_part_1'].tolist())
                self.assertEqual([42], replay.index.tolist())

    def test_loading_another_file_and_clear_all_discard_old_operations(self):
        source = pd.DataFrame({'Raw': ['AB  001  ZZ'], 'Qty': [5]})
        for file_type in ('history', 'plan'):
            self.load_frame(file_type, source)
            self.split(file_type, 'Raw')
        self.load_frame('history', source)
        self.assertEqual([], self.app.history_transform_configs)
        self.assertTrue(self.app.plan_transform_configs)
        self.app.clear_all()
        self.assertEqual([], self.app.history_transform_configs)
        self.assertEqual([], self.app.plan_transform_configs)

    def test_missing_or_disabled_split_sources_raise_an_actionable_error(self):
        source = pd.DataFrame({'Raw': ['AB  001  ZZ'], 'Qty': [5]})
        self.load_frame('history', source)
        self.split('history', 'Raw')
        self.concatenate('history', ['Raw_part_2', 'Raw_part_1'], 'Key')
        with self.assertRaisesRegex(ValueError, 'missing source column\\(s\\): Raw'):
            self.app.apply_column_transformations(source.drop(columns='Raw'), 'history')
        self.app.history_split_enabled.set(False)
        with self.assertRaisesRegex(ValueError, 'Text-to-Columns is enabled'):
            self.app.apply_column_transformations(source, 'history')


if __name__ == '__main__':
    unittest.main()
