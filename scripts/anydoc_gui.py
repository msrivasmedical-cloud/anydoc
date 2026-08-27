#!/usr/bin/env python3
"""Interfaz grafica: elegir carpeta, agrupar archivos por formato y convertirlos con anydoc.

Uso: python scripts/anydoc_gui.py
Requiere Node.js/npx en el PATH (se usa `npx @firecrawl/anydoc` como motor de conversion).
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# Extension -> nombre de grupo mostrado en la UI. El CLI detecta el formato
# real por contenido/extension solo, asi que aqui solo agrupamos para mostrar.
EXTENSION_GROUPS = {
    ".doc": "Word (.doc)",
    ".docx": "Word (.docx)",
    ".docm": "Word (.docx)",
    ".ppt": "PowerPoint (.ppt)",
    ".pps": "PowerPoint (.ppt)",
    ".pot": "PowerPoint (.ppt)",
    ".pptx": "PowerPoint (.pptx)",
    ".pptm": "PowerPoint (.pptx)",
    ".ppsx": "PowerPoint (.pptx)",
    ".ppsm": "PowerPoint (.pptx)",
    ".xls": "Excel (.xlsx)",
    ".xlsx": "Excel (.xlsx)",
    ".xlsm": "Excel (.xlsx)",
    ".xlsb": "Excel (.xlsx)",
    ".odt": "OpenDocument texto (.odt)",
    ".ods": "OpenDocument hoja (.ods)",
    ".odp": "OpenDocument presentacion (.odp)",
    ".rtf": "RTF (.rtf)",
    ".epub": "EPUB (.epub)",
    ".csv": "CSV (.csv)",
    ".pdf": "PDF (.pdf)",
}


class AnydocGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("anydoc - conversor de documentos a Markdown")
        self.geometry("820x560")

        self.selected_folder: Path | None = None
        self.recursive = tk.BooleanVar(value=True)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None

        self._build_widgets()
        self.after(100, self._drain_log_queue)

    def _build_widgets(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        ttk.Button(top, text="Seleccionar carpeta...", command=self.on_select_folder).pack(side="left")
        self.folder_label = ttk.Label(top, text="Ninguna carpeta seleccionada", foreground="gray")
        self.folder_label.pack(side="left", padx=10)

        ttk.Checkbutton(
            top, text="Incluir subcarpetas", variable=self.recursive, command=self.on_rescan
        ).pack(side="right")

        # Arbol: grupos de formato -> archivos individuales
        tree_frame = ttk.Frame(self, padding=(10, 0))
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=("count",), show="tree headings")
        self.tree.heading("#0", text="Formato / archivo")
        self.tree.heading("count", text="Cantidad")
        self.tree.column("count", width=90, anchor="center")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

        # Salida
        out_frame = ttk.Frame(self, padding=10)
        out_frame.pack(fill="x")
        ttk.Label(out_frame, text="Carpeta de salida:").pack(side="left")
        self.output_var = tk.StringVar()
        ttk.Entry(out_frame, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(out_frame, text="...", width=3, command=self.on_pick_output).pack(side="left")

        # Botones de accion
        action_frame = ttk.Frame(self, padding=10)
        action_frame.pack(fill="x")
        self.run_button = ttk.Button(
            action_frame, text="Ejecutar anydoc", command=self.on_run, state="disabled"
        )
        self.run_button.pack(side="left")
        self.status_label = ttk.Label(action_frame, text="")
        self.status_label.pack(side="left", padx=10)

        # Log
        log_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=10, state="disabled", wrap="word")
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_vsb.pack(side="left", fill="y")

    # ---- seleccion y escaneo ----

    def on_select_folder(self) -> None:
        folder = filedialog.askdirectory(title="Selecciona la carpeta con documentos")
        if not folder:
            return
        self.selected_folder = Path(folder)
        self.folder_label.config(text=str(self.selected_folder), foreground="black")
        self.output_var.set(str(self.selected_folder / "anydoc_markdown"))
        self.on_rescan()

    def on_pick_output(self) -> None:
        folder = filedialog.askdirectory(title="Selecciona la carpeta de salida")
        if folder:
            self.output_var.set(folder)

    def on_rescan(self) -> None:
        if self.selected_folder is None:
            return
        self.tree.delete(*self.tree.get_children())

        groups: dict[str, list[Path]] = {}
        if self.recursive.get():
            walker = self.selected_folder.rglob("*")
        else:
            walker = self.selected_folder.glob("*")
        for path in walker:
            if not path.is_file():
                continue
            group = EXTENSION_GROUPS.get(path.suffix.lower())
            if group is None:
                continue
            groups.setdefault(group, []).append(path)

        total = 0
        for group_name in sorted(groups):
            files = sorted(groups[group_name])
            total += len(files)
            group_id = self.tree.insert("", "end", text=group_name, values=(len(files),), open=False)
            for f in files:
                rel = f.relative_to(self.selected_folder)
                self.tree.insert(group_id, "end", text=str(rel), values=("",))

        self.status_label.config(text=f"{total} archivo(s) compatible(s) encontrados")
        self.run_button.config(state="normal" if total else "disabled")

    # ---- ejecucion ----

    def on_run(self) -> None:
        if self.selected_folder is None or self.worker and self.worker.is_alive():
            return
        files = [
            self.selected_folder / self.tree.item(child, "text")
            for group in self.tree.get_children()
            for child in self.tree.get_children(group)
        ]
        if not files:
            messagebox.showinfo("anydoc", "No hay archivos para convertir.")
            return

        output_dir = Path(self.output_var.get() or (self.selected_folder / "anydoc_markdown"))
        output_dir.mkdir(parents=True, exist_ok=True)

        self.run_button.config(state="disabled")
        self._clear_log()
        self.worker = threading.Thread(
            target=self._convert_all, args=(files, output_dir), daemon=True
        )
        self.worker.start()

    def _convert_all(self, files: list[Path], output_dir: Path) -> None:
        npx = "npx.cmd" if os.name == "nt" else "npx"
        ok, failed = 0, 0
        for src in files:
            rel = src.relative_to(self.selected_folder)
            dest = (output_dir / rel).with_suffix(".md")
            dest.parent.mkdir(parents=True, exist_ok=True)
            self.log_queue.put(f"Convirtiendo {rel} ...")
            try:
                result = subprocess.run(
                    [npx, "-y", "@firecrawl/anydoc", str(src), "-o", str(dest)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except Exception as exc:  # subprocess/OS errors
                failed += 1
                self.log_queue.put(f"  ERROR ejecutando anydoc para {rel}: {exc}")
                continue

            if result.returncode == 0:
                ok += 1
                self.log_queue.put(f"  OK -> {dest.relative_to(output_dir)}")
            else:
                failed += 1
                message = (result.stderr or result.stdout or "error desconocido").strip()
                self.log_queue.put(f"  FALLO {rel}: {message}")

        self.log_queue.put(f"Listo: {ok} convertido(s), {failed} fallido(s).")
        self.log_queue.put("__DONE__")

    # ---- utilidades de log/hilo ----

    def _clear_log(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _drain_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__DONE__":
                    self.run_button.config(state="normal")
                    continue
                self.log_text.config(state="normal")
                self.log_text.insert("end", line + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)


def main() -> int:
    app = AnydocGUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
