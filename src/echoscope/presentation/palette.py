from tkinter import ttk

PALETTES = {
    "light": ("#f3f6fa", "#ffffff", "#172438", "#205d9c", "#dbe8f8", "#c0ccda"),
    "dark": ("#131a24", "#1e2835", "#e9eff8", "#326ba9", "#294762", "#42546a"),
}
HIGHLIGHTS = {
    "light": {
        "info": "#fff1bc",
        "important": "#ffe0a2",
        "critical": "#ffd2d5",
        "review": "#e8ddfa",
    },
    "dark": {"info": "#514418", "important": "#633f1f", "critical": "#652f40", "review": "#463767"},
}


def paint(root, name, *editors):
    background, surface, ink, accent, selected, border = PALETTES[name]
    root.configure(background=background)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        ".",
        background=background,
        foreground=ink,
        bordercolor=border,
        lightcolor=surface,
        darkcolor=surface,
        troughcolor=background,
        insertcolor=ink,
        selectbackground=selected,
        selectforeground=ink,
    )
    style.configure("TLabel", font=("Segoe UI", 10))
    style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
    style.configure("Heading.TLabel", font=("Segoe UI", 12, "bold"))
    style.configure("TButton", padding=(10, 6), font=("Segoe UI", 10))
    style.map("TButton", background=[("active", selected)])
    style.configure("Primary.TButton", background=accent, foreground="white")
    style.map("Primary.TButton", background=[("active", accent), ("disabled", border)])
    style.configure(
        "Treeview",
        background=surface,
        fieldbackground=surface,
        foreground=ink,
        rowheight=29,
        font=("Segoe UI", 10),
    )
    style.configure("Treeview.Heading", background=background, foreground=ink)
    style.map("Treeview", background=[("selected", selected)], foreground=[("selected", ink)])
    style.configure("TNotebook.Tab", padding=(11, 7), font=("Segoe UI", 10))
    style.map("TNotebook.Tab", background=[("selected", selected)], foreground=[("selected", ink)])
    for control in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(control, fieldbackground=surface, foreground=ink, arrowcolor=ink)
        style.map(control, fieldbackground=[("readonly", surface)], foreground=[("readonly", ink)])
    root.option_add("*TCombobox*Listbox.background", surface)
    root.option_add("*TCombobox*Listbox.foreground", ink)
    for editor in editors:
        editor.configure(
            background=surface,
            foreground=ink,
            insertbackground=ink,
            selectbackground=selected,
            selectforeground=ink,
        )
    for kind, color in HIGHLIGHTS[name].items():
        editors[0].tag_configure(kind, background=color, foreground=ink)
