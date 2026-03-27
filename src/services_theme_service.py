from src.render.theme import load_theme


def resolve_theme_name(cfg, override_theme: str | None) -> str:
    theme_name = override_theme if override_theme is not None else cfg.theme
    if theme_name == "random":
        from src.render.random_theme import pick_random_theme
        theme_name = pick_random_theme(
            include=cfg.random_theme.include,
            exclude=cfg.random_theme.exclude,
            output_dir=cfg.output_dir,
        )
    return theme_name


def resolve_theme(theme_name: str):
    return load_theme(theme_name)
