# doc_parser.py (Parser de Documentación Markdown)
#
# RELACIÓN CON code_parser.py
# ─────────────────────────────────────────────────────────────────────────────
# code_parser.py  →  Recorre archivos *.py y extrae *unidades de código*:
#                     funciones, clases, métodos. Cada unidad recibe un
#                     identificador estable con el esquema:
#                         "<file_path>::<function_or_class_name>"
#                     Por ejemplo: "src/api/routes.py::create_user"
#
# doc_parser.py   →  Recorre archivos *.md y extrae *secciones de documentación*:
#                     cada sección delimitada por un encabezado Markdown (#, ##, …).
#                     Cada sección recibe un identificador estable con el esquema:
#                         "<file_path>::<heading_path>"
#                     Por ejemplo: "docs/api.md::API Reference > Endpoints > POST /users"
#
# El campo `code_references` de cada sección es el puente hacia code_parser.py:
# contiene los nombres de funciones/clases que el texto de la sección menciona
# y que existen en los chunks devueltos por CodeParser. El grafo final
# (construido en graph_builder.py) usa este campo + similitud de embeddings
# para trazar los vínculos code ↔ docs.
# ─────────────────────────────────────────────────────────────────────────────
#
# Responsabilidad clave:
#   1. Dividir archivos Markdown en secciones por encabezado.
#   2. Asignar a cada sección su "heading path" jerárquico
#      (ej. "Configuration > Environment Variables").
#   3. Detectar menciones a símbolos de código dentro del texto:
#      nombres de función/clase/CLI, backtick-references e inline-code.
#   4. Devolver una lista de dicts con el mismo estilo de salida que
#      CodeParser, de modo que ambos sean consumibles de forma uniforme
#      por el graph_builder y el embedder.

import re
from pathlib import Path
from typing import Dict, List, Any, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Constantes y patrones de búsqueda
# ──────────────────────────────────────────────────────────────────────────────

# Detecta líneas de encabezado Markdown: de # (h1) a ###### (h6)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)", re.MULTILINE)

# Captura cualquier token delimitado por backticks (``código`` o `código`)
# Estos suelen ser referencias explícitas a funciones, clases, comandos, etc.
_BACKTICK_RE = re.compile(r"`{1,2}([^`\n]+)`{1,2}")

# Captura patrones de funciones/métodos Python: word( o word.word(
_FUNCTION_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\(")

# Captura clases que empiezan con mayúscula (PascalCase / CamelCase)
_CLASS_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]+)\b")


class DocParser:
    """
    Parser de documentación Markdown para el sistema Self-Healing.

    Recorre todos los archivos .md de un repositorio y los divide en secciones
    delimitadas por encabezados. Cada sección se entrega como un dict con la
    misma estructura que los chunks producidos por `CodeParser`, lo que permite
    que `graph_builder.py` los procese de forma uniforme.

    Parámetros
    ----------
    repo_path : str
        Ruta raíz del repositorio a analizar.
    known_symbols : list[str], opcional
        Lista de nombres de funciones/clases extraídos previamente por
        `CodeParser`. Si se proporciona, el campo `code_references` de cada
        sección sólo incluirá los símbolos que *realmente existen* en el código,
        reduciendo falsos positivos en la búsqueda heurística.
    """

    def __init__(self, repo_path: str, known_symbols: Optional[List[str]] = None):
        self.repo_path = Path(repo_path)
        # Conjunto de símbolos de código conocidos (nombres de funciones/clases).
        # Viene de los chunks producidos por CodeParser:
        #   known_symbols = [chunk["name"] for chunk in code_chunks]
        self.known_symbols: set[str] = set(known_symbols or [])

    # ──────────────────────────────────────────────────────────────────────────
    # API pública — espejo de CodeParser.parse_repository()
    # ──────────────────────────────────────────────────────────────────────────

    def parse_repository(self) -> List[Dict[str, Any]]:
        """
        Recorre el repositorio buscando archivos .md y extrae sus secciones.

        Returns
        -------
        list[dict]
            Lista de secciones de documentación. Cada dict tiene la misma
            forma que los chunks de code_parser.py para ser procesados
            uniformemente por graph_builder.py.

        Ejemplo de salida
        -----------------
        [
            {
                "id":              "docs/setup.md::Installation > Requirements",
                "file_path":       "docs/setup.md",
                "type":            "doc_section",
                "heading":         "Requirements",
                "heading_path":    "Installation > Requirements",
                "heading_level":   3,
                "content":         "You need Python 3.11+...",
                "code_references": ["install_dependencies", "Config"],
                "lineno":          42,
            },
            ...
        ]
        """
        doc_sections: List[Dict[str, Any]] = []

        for file_path in self.repo_path.glob("**/*.md"):
            # Ignorar carpetas ocultas (.git, .github, etc.) — mismo criterio
            # que CodeParser para mantener consistencia en qué archivos se
            # procesan dentro del repositorio.
            if any(part.startswith(".") for part in file_path.parts):
                continue
            doc_sections.extend(self._parse_file(file_path))

        return doc_sections

    # ──────────────────────────────────────────────────────────────────────────
    # Lógica interna — espejo de CodeParser._parse_file()
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_file(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Divide un archivo Markdown en secciones delimitadas por encabezados y
        construye el dict de metadatos para cada una.

        A diferencia de code_parser.py (que usa el módulo `ast` para un árbol
        sintáctico completo), aquí el "árbol" es más simple: una pila de
        encabezados activos que representa la ruta jerárquica actual.

        Parámetros
        ----------
        file_path : Path
            Ruta absoluta al archivo .md.

        Returns
        -------
        list[dict]
            Secciones extraídas del archivo.
        """
        sections: List[Dict[str, Any]] = []
        relative_path = str(file_path.relative_to(self.repo_path))

        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"Error leyendo {relative_path}: {e}")
            return sections

        # Dividir el texto usando los encabezados como delimitadores
        # `_split_by_headings` devuelve tuplas (level, heading_text, content, lineno)
        heading_blocks = self._split_by_headings(raw_text)

        # Pila de encabezados activos por nivel: índice = nivel (1-6)
        # Nos permite construir el "heading_path" jerárquico de cada sección,
        # análogo al "stable_id" de code_parser.py pero para docs.
        heading_stack: List[Optional[str]] = [None] * 7  # índices 1..6

        for level, heading_text, content, lineno in heading_blocks:
            # Actualizar la pila: al entrar en un nivel N, borrar los sub-niveles > N
            heading_stack[level] = heading_text
            for deeper_level in range(level + 1, 7):
                heading_stack[deeper_level] = None

            # Construir el heading_path jerárquico, p.ej. "API > Endpoints > POST /users"
            heading_path = self._build_heading_path(heading_stack)

            # Identificador estable: mismo esquema que code_parser.py
            #   code_parser → "<file_path>::<function_name>"
            #   doc_parser  → "<file_path>::<heading_path>"
            stable_id = f"{relative_path}::{heading_path}"

            # Detectar referencias a símbolos de código dentro del contenido
            code_references = self._extract_code_references(content)

            sections.append(
                {
                    # ── Campos espejo de code_parser.py ──────────────────────
                    "id":        stable_id,      # identificador estable único
                    "file_path": relative_path,  # ruta relativa al repo root
                    "type":      "doc_section",  # análogo a "function" / "class"
                    "name":      heading_text,   # análogo al nombre de la fn/clase
                    "lineno":    lineno,         # número de línea del encabezado
                    # ── Campos específicos de doc_parser ─────────────────────
                    "heading":         heading_text,   # texto del encabezado actual
                    "heading_path":    heading_path,   # ruta jerárquica completa
                    "heading_level":   level,          # profundidad: 1=H1, 2=H2, …
                    "content":         content.strip(), # texto de la sección (sin heading)
                    "code_references": code_references, # puente hacia code_parser chunks
                }
            )

        return sections

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _split_by_headings(
        self, text: str
    ) -> List[tuple[int, str, str, int]]:
        """
        Divide el texto Markdown en bloques, uno por encabezado.

        Estrategia: encuentra todos los encabezados con su posición en el texto,
        luego el contenido de cada sección es el texto entre ese encabezado y
        el siguiente.

        Returns
        -------
        list of (level, heading_text, section_content, lineno)
        """
        blocks: List[tuple[int, str, str, int]] = []
        lines = text.splitlines(keepends=True)

        # Índice de líneas: mapear posición de carácter → número de línea
        # (necesario para reportar `lineno`, igual que code_parser.py)
        char_to_line: Dict[int, int] = {}
        pos = 0
        for line_num, line in enumerate(lines, start=1):
            for _ in line:
                char_to_line[pos] = line_num
                pos += 1

        matches = list(_HEADING_RE.finditer(text))

        for i, match in enumerate(matches):
            level = len(match.group(1))          # número de '#' = nivel
            heading_text = match.group(2).strip()

            # Contenido: desde el final de esta línea de encabezado hasta el
            # inicio del próximo encabezado (o el final del archivo)
            content_start = match.end()
            content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[content_start:content_end]

            # Número de línea del encabezado
            lineno = char_to_line.get(match.start(), 1)

            blocks.append((level, heading_text, content, lineno))

        return blocks

    def _build_heading_path(self, stack: List[Optional[str]]) -> str:
        """
        Construye la ruta jerárquica de encabezados activos.

        Por ejemplo, si la pila tiene:
            nivel 1 → "Configuration"
            nivel 2 → "Environment Variables"
            nivel 3 → None

        El resultado es: "Configuration > Environment Variables"

        Esto es el análogo de code_parser.py al construir el stable_id
        concatenando file_path + "::" + function_name; aquí concatenamos
        los encabezados activos con " > ".
        """
        active_headings = [h for h in stack[1:] if h is not None]
        return " > ".join(active_headings) if active_headings else "root"

    def _extract_code_references(self, content: str) -> List[str]:
        """
        Detecta referencias a símbolos de código dentro del texto de una sección.

        Estrategia en dos capas (misma filosofía que el paso 3 del plan:
        heurísticas primero, embeddings después):

        Capa 1 — Heurística explícita:
            Extrae todo lo que aparece entre backticks (``función()`` o `Clase`).
            Estos son los candidatos más confiables porque el autor del doc
            los marcó explícitamente como código.

        Capa 2 — Heurística de patrón:
            Si se proporcionaron `known_symbols` (los nombres extraídos por
            CodeParser), busca coincidencias de esos nombres en texto libre,
            incluyendo llamadas de función y nombres PascalCase.
            Esto captura menciones informales como "la función create_user"
            que no están en backticks.

        Returns
        -------
        list[str]
            Lista deduplicada de símbolos de código referenciados.
            Graph_builder.py usará esta lista para crear los vínculos
            heurísticos code ↔ docs antes de aplicar los embeddings.
        """
        found: set[str] = set()

        # ── Capa 1: backtick references ───────────────────────────────────────
        for match in _BACKTICK_RE.finditer(content):
            token = match.group(1).strip()
            # Limpiar llamadas de función: "create_user()" → "create_user"
            token = token.rstrip("()")
            # Limpiar accesos de atributo para quedarnos con el nombre base:
            # "requests.get" → "get"  (en docs suele mencionarse la librería)
            base_token = token.split(".")[-1]
            if base_token:
                found.add(base_token)
            # Si el token completo coincide con un símbolo conocido, añadir también
            if token in self.known_symbols:
                found.add(token)

        # ── Capa 2: coincidencia con known_symbols en texto libre ─────────────
        # Sólo se ejecuta si se proporcionó la lista de símbolos conocidos
        # (evita falsos positivos cuando known_symbols está vacío).
        if self.known_symbols:
            # Buscar llamadas de función en el texto
            for match in _FUNCTION_CALL_RE.finditer(content):
                func_name = match.group(1).split(".")[-1]
                if func_name in self.known_symbols:
                    found.add(func_name)

            # Buscar nombres PascalCase que coincidan con clases conocidas
            for match in _CLASS_NAME_RE.finditer(content):
                class_name = match.group(1)
                if class_name in self.known_symbols:
                    found.add(class_name)

        return sorted(found)  # ordenado para salida determinista


# ──────────────────────────────────────────────────────────────────────────────
# Ejemplo de uso rápido (espejo del bloque __main__ de code_parser.py)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Uso básico: sin símbolos conocidos (sólo heurística de backticks)
    parser = DocParser(repo_path="./")
    sections = parser.parse_repository()
    print(f"Se encontraron {len(sections)} secciones de documentación.")
    for section in sections[:3]:  # mostrar las primeras 3 como muestra
        print(
            f"  [{section['heading_level']}] {section['heading_path']!r}"
            f"  →  refs: {section['code_references']}"
        )

    # Uso avanzado: con símbolos conocidos extraídos de CodeParser
    # from src.mapping.code_parser import CodeParser
    # code_chunks = CodeParser(repo_path="./").parse_repository()
    # known = [chunk["name"] for chunk in code_chunks]
    # parser = DocParser(repo_path="./", known_symbols=known)
    # sections = parser.parse_repository()