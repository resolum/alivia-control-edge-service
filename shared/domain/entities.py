from dataclasses import dataclass

@dataclass(frozen=True)
class OperationResult:
    success: bool
    code: str
    message: str = ""
