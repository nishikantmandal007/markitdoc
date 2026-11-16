class MarkitDocError(Exception):
    pass

class UnsupportedFormatError(MarkitDocError, ValueError):
    pass

class EmptyDocumentError(MarkitDocError, ValueError):
    pass

class RenderError(MarkitDocError):
    pass

class ThemeError(MarkitDocError, ValueError):
    pass
