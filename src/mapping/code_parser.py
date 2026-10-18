# code_parser.py (Parser de código fuente)
# Qué hace: Se encarga de recorrer el repositorio analizando archivos de código (usando por ejemplo librerías como ast de Python) para extraer las unidades semánticas: firmas de funciones con docstrings, definiciones de clases, endpoints de API y esquemas.

# Responsabilidad clave: Generar los identificadores estables combinando (file path + function/class name).

import ast
from pathlib import Path
from typing import Dict, List, Any


class CodeParser:
    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def parse_repository(self) -> List[Dict[str, Any]]:
        """Recorre el repositorio buscando archivos .py y extrae sus chunks semánticos."""
        code_chunks = []
        for file_path in self.repo_path.glob("**/*.py"):
            # Opcional: ignorar entornos virtuales o carpetas ocultas
            if any(part.startswith(".") for part in file_path.parts):
                continue
            code_chunks.extend(self._parse_file(file_path))
        return code_chunks

    def _parse_file(self, file_path: Path) -> List[Dict[str, Any]]:
        chunks = []
        relative_path = str(file_path.relative_to(self.repo_path))

        try:
            source_code = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source_code)
        except Exception as e:
            print(f"Error parseando {relative_path}: {e}")
            return chunks

        # Recorremos el árbol sintáctico (AST) en busca de clases y funciones
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Identificador estable: file path + function name
                stable_id = f"{relative_path}::{node.name}"
                docstring = ast.get_docstring(node) or ""

                chunks.append(
                    {
                        "id": stable_id,
                        "file_path": relative_path,
                        "type": "function",
                        "name": node.name,
                        "docstring": docstring,
                        "lineno": node.lineno,
                    }
                )

            elif isinstance(node, ast.ClassDef):
                # Identificador estable: file path + class name
                stable_id = f"{relative_path}::{node.name}"
                docstring = ast.get_docstring(node) or ""

                chunks.append(
                    {
                        "id": stable_id,
                        "file_path": relative_path,
                        "type": "class",
                        "name": node.name,
                        "docstring": docstring,
                        "lineno": node.lineno,
                    }
                )

        return chunks


# Ejemplo de uso rápido:
if __name__ == "__main__":
    parser = CodeParser(repo_path="./")
    chunks = parser.parse_repository()
    print(f"Se encontraron {len(chunks)} fragmentos de código.")