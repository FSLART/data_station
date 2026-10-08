"""Run with xvfb-run to exercise the Error tests tab without starting processes."""
import os
import queue
from types import SimpleNamespace
import unittest

from sim.admin_panel import Panel


@unittest.skipUnless(os.environ.get('DISPLAY'), 'requires Tk display or xvfb-run')
class FaultPanelGuiTest(unittest.TestCase):
    def test_tab_multiselection_preview_and_commands(self):
        import tkinter as tk
        root = tk.Tk()
        commands = []
        try:
            backend = SimpleNamespace(events=queue.Queue(), submit=lambda *args: commands.append(args))
            panel = Panel(root, backend)
            self.assertEqual(panel.tabs.tab(1, 'text'), 'Error tests')
            panel.tabs.select(1)
            panel.fault_tree.selection_set(['Low SOC', 'Low LV voltage'])
            root.update()
            self.assertEqual(set(panel.fault_args()[0]), {'Low SOC', 'Low LV voltage'})
            self.assertIn('SOC_Float = 10', panel.fault_preview.get('1.0', 'end'))
            self.assertIn('IVT_Result_U3 = 22000', panel.fault_preview.get('1.0', 'end'))
            def buttons(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == 'TButton':
                        yield child
                    yield from buttons(child)
            for button in buttons(root):
                if button.cget('text') in ('Apply selected errors', 'Clear errors / restore previous'):
                    button.invoke()
            self.assertEqual(commands[0][0], 'fault')
            self.assertEqual(commands[1], ('end_test',))
        finally:
            for callback in root.tk.call('after', 'info'):
                root.after_cancel(callback)
            root.destroy()
