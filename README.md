# nuBoard

KiCad 10 hardware projects copied from the working `nu68020/nuBoard` directory.

| Project | Open this file |
| --- | --- |
| Main board | `hardware/main-board/nuBoard.kicad_pro` |
| Daughter board template | `hardware/daughter-template/nuDaughter.kicad_pro` |
| 68000 daughter board | `hardware/68000/68000.kicad_pro` |

Each daughter project has its own `nuBoard.kicad_sym`, `nuBoard.pretty`, and
project-relative library tables. Either directory can be copied independently;
the only libraries required outside it are the default KiCad 10 libraries.
Keep these local libraries with the project when copying or distributing it.
The main board also uses project-relative custom libraries and bundled models.

To create a daughter board, copy the entire `hardware/daughter-template` directory,
or select it with KiCad's New Project from Template dialog. Its `meta` directory
contains template metadata. Keep the library filenames as `nuBoard.*`; KiCad
renames files containing `nuDaughter` when creating a project from the template.
Filename-specific sheet metadata and annotation history have been removed from
the template settings so new projects can be renamed and annotated cleanly.

Existing production exports, notes, design blocks, models, and supporting data
are preserved beside their projects. Production exports are historical snapshots;
regenerate them before fabrication. Backups and personal editor state were copied
locally but are excluded from Git. The original source directory is untouched.

## Konnect MCP

Open your MCP client from the repository root. `.mcp.json` configures Konnect for
compatible clients; `.codex/config.toml` configures it for Codex, following the
[official MCP configuration documentation](https://developers.openai.com/codex/mcp/).
Codex loads project configuration for trusted projects. Restart the client after
opening this repository to load the server.

Both configurations run `sh scripts/konnect.sh`, which uses `bin/konnect` when
present, otherwise `konnect` on PATH. This checkout includes a local copy of the
existing Konnect v0.2.0 macOS arm64 executable in `bin/konnect`; the binary is
ignored by Git. On another machine, install a compatible Konnect executable on
PATH or place it in `bin/konnect` and make it executable.

Check the installation with `sh scripts/konnect.sh --version` and
`sh scripts/konnect.sh status`. For live PCB operations, open the intended PCB in
KiCad and enable its IPC API. Explicitly select the intended project when using
Konnect because this repository contains three boards.
