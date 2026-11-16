from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Options:
    gotenberg_url: str | None = None
    cache_folder: Path | None = None
    user_agent: str | None = None
    style_folders: tuple = ()


options_context = ContextVar("markitdoc_options", default=Options())


# returns the options active in the current context
def options_in_use():
    return options_context.get()


# applies options for a block and restores the previous context afterwards
@contextmanager
def using_options(options):
    token = options_context.set(options)
    try:
        yield
    finally:
        options_context.reset(token)
