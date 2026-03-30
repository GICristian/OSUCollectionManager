# OSC — manager colecții osu!Collector

Aplicație desktop (**CustomTkinter**) pentru [osu!Collector](https://osucollector.com):

- **Import nou**: ID sau URL colecție → încarci metadata → setezi numele în osu → **Rulează import** (descărcare `.osz` opțională + scriere **Realm** / **collection.db**).
- **Sidebar**: lista colecțiilor deja din baza ta (**lazer** prin JSON de la utilitarul C#, **stable** din `collection.db`). Click pe o colecție = sumar rapid.
- **Setări** (salvate în `%AppData%\OSC\settings.json`): client implicit, folder date osu, căi Realm / `collection.db`, folder descărcări.

## Log diagnostic (`OSC_diagnostic.log`)

OSC scrie un jurnal **append-only** pentru depanare (API, Realm utilitar, sidebar, descărcări, excepții în coada UI Tk):

- **Rulare din sursă (dev):** `OSC_diagnostic.log` în **rădăcina repo-ului** (lângă `osc_collector/`), același nivel ca `readme/`.
- **Build PyInstaller:** același nume de fișier **în folderul cu `OSC.exe`** (ex. `dist\OSC\OSC_diagnostic.log`).

La peste ~4 MB, fișierul curent este redenumit în `OSC_diagnostic.log.prev` și se începe unul nou. Poți atașa log-ul la rapoarte de bug sau îl poți deschide în editor ca să vezi ultimele linii cu timestamp și nivel (`INFO` / `WARN` / `ERROR`).

**Liniile `[DEBUG]` (flux detaliat UI + worker + API + mirror + librărie):** activează din **Setări** → bifa „Log diagnostic detaliat”, sau pornește aplicația cu variabila de mediu `OSC_DEBUG_LOG=1` (sau `true` / `yes` / `on`). Fără această opțiune, în fișier rămân doar evenimentele INFO/WARN/ERROR (mai puțin zgomot). Cu DEBUG vezi: coada UI Tk, apeluri sidebar/import, thread-uri de fundal, fiecare set descărcat de la mirror, request-uri osu!Collector, intrări în `library_service` / utilitar Realm etc.

## Colecții: osu!lazer vs osu!stable

Cele două clienți **nu** folosesc același fișier; lista din joc poate diferi complet între lazer și stable.

### osu!lazer

- **Unde:** folderul principal de date al jocului — de obicei `%AppData%\osu` pe Windows (`%AppData%` = *Roaming*) și `~/.local/share/osu` pe Linux. Poți muta datele din **Setări → Conținut** în lazer.
- **Fișier:** bază **Realm** numită în practică `client.realm` sau `client_<versiune_schema>.realm` (ex. `client_51.realm`). În codul oficial, colecțiile sunt obiecte `BeatmapCollection` cu liste de **hash-uri MD5** ale beatmap-urilor, nu nume de fișiere.
- **În joc:** gestionare din zona de beatmap-uri / opțiuni (ex. **Manage Beatmaps**).
- **Backup:** recomandat să copiezi **întreg** folderul de date; colecțiile sunt legate de același `client_*.realm` ca restul stării.
- **Context comunitate:** [How are collections stored? (reddit)](https://www.reddit.com/r/osugame/comments/1hnm6gy/how_are_collections_stored/) — discuție despre `client.realm`.
- **Beatmap-urile** (fișierele propriu-zise) în lazer stau altfel decât în stable (de ex. sub `files/` cu hash-uri), nu ca folderul `Songs` din stable — vezi [comentariul din osu#3910](https://github.com/ppy/osu/issues/3910#issuecomment-543239384).
- **„E criptat?”** [User file storage](https://github.com/ppy/osu/wiki/User-file-storage) descrie stocarea prin hash-uri în `files/` ca să nu poți modifica ușor fișierele; **fișierul Realm** în sine, în codul public `RealmAccess` din [ppy/osu](https://github.com/ppy/osu/blob/master/osu.Game/Database/RealmAccess.cs), este deschis cu `RealmConfiguration` **fără** `EncryptionKey` — e format binar Realm (nu text), nu o „parolă” pe care trebuie să o pui în OSC. Dacă ai **0 colecții** în sidebar dar le vezi în joc, de obicei OSC citește **alt** `client.realm` decât jocul (ex. folder de date mutat în **Setări → Conținut** în lazer).

OSC, pe **Lazer**, citește/scrie acel fișier **Realm** prin utilitarul `OscLazerRealmImport` (nu prin `collection.db`). Utilitarul folosește **aceeași versiune de schemă** ca jocul (`schema_version` din `RealmAccess`); dacă ppy/osu o crește, trebuie actualizat `OscRealm.OsuSchemaVersion` în repo. Listarea și importul folosesc Realm **dinamic** (`IsDynamic`), ca să nu valideze un model C# împotriva fișierului în **read-only** (altfel poate apărea eroare de tip „read-only schema mode” dacă diferențele față de joc sunt minime). Modelul tipizat `BeatmapCollection` rămâne în repo pentru teste de regresie.

### osu!stable

- **Unde:** de obicei `%LocalAppData%\osu!\collection.db` (format [legacy collection.db](https://github.com/ppy/osu/wiki/Legacy-database-file-structure)).
- OSC, pe **Stable**, folosește direct acest `collection.db`.

## Cerințe

- Python 3.11+
- **osu!lazer**: din sursă, [.NET 8 SDK](https://dotnet.microsoft.com/download) pentru `tools/OscLazerRealmImport` (import + list în sidebar). **Build-ul `.exe`** înglobează utilitarul C# self-contained — destinatarul arhivei **nu** trebuie să aibă .NET instalat.

## Setup

```powershell
cd d:\Work\OSC
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

## Teste

```powershell
python -m pytest tests -v
dotnet test tools\OscLazerRealmImport.Tests\OscLazerRealmImport.Tests.csproj -c Release
```

## Rulare

```powershell
python -m osc_collector
```

Implicit: **Ghid rapid** — pași 1–5 (link → încarcă → descarcă manual → deschide folder .osz → adaugă colecția manual). Bifează **Mod avansat (developer)** în bara de sus pentru vechea interfață cu un singur „Rulează import” și opțiuni combinate. Preferința se salvează în `settings.json`.

## Executabil Windows (.exe)

Cu **.NET 8 SDK**, venv cu `requirements-dev.txt` și din rădăcina `OSC`:

```powershell
.\build_exe.ps1
```

Rezultatul este folderul **`dist\OSC\`**: `OSC.exe` + folderul PyInstaller (`_internal\` …) + **întreg output-ul** `dotnet publish` al lui `OscLazerRealmImport` (self-contained **win-x64**), toate **în același folder** ca `OSC.exe`. Nu copia doar `OSC.exe` — lipsesc `_internal` și fișierele .NET/Realm.

### Ce trimiți unui prieten (fără Python, fără .NET pe PC-ul lui)

- **Recomandat:** dacă publici pe GitHub, trimite link la **Releases**; prietenul descarcă **`OSC_x.y.z_Setup.exe`**, instalează din asistent, pornește OSC din Meniul Start (sau desktop, dacă a bifat).
- **Portabil (zip):** rulezi `.\build_exe.ps1`, apoi `.\package_osc_release.ps1` — zip cu folderul `OSC`; extrage tot și dublu-clic pe **`OSC.exe`**. Setările merg în `%AppData%\OSC\` (nu lângă exe).

**Cerințe pe PC destinatar:** Windows 10/11 **64-bit**. Dimensiunea arhivei e mai mare decât la publish „framework-dependent”, pentru că include runtime-ul .NET al utilitarului Realm.

### GitHub: release doar cu descărcare

1. **Prima dată — repo + push automat (recomandat):** instalezi [GitHub CLI](https://cli.github.com/) dacă lipsește (`winget install --id GitHub.cli -e`). În PowerShell din folderul proiectului:
   ```powershell
   cd d:\Work\OSC
   gh auth login -h github.com -p https -w
   .\create_and_push_github.ps1
   ```
   `gh auth login` deschide browserul o dată. **Contul conectat în Cursor sau pe github.com nu înlocuiește acest pas** — CLI-ul `gh` își salvează token-ul separat (folder `%AppData%\GitHub CLI`). După login, verifică: `gh auth status`. Scriptul **`create_and_push_github.ps1`** creează repo-ul public **`OSUCollectionManager`** (dacă lipsește), setează `origin` la **HTTPS** și face **`git push -u origin main`**. Poți folosi și variabila de mediu **`GH_TOKEN`** (PAT cu drept `repo`) în loc de `gh auth login`.
2. **Manual:** poți crea pe GitHub un repo gol **`OSUCollectionManager`**, apoi `git remote add` / `git push` ca înainte. Link așteptat: [github.com/GICristian/OSUCollectionManager](https://github.com/GICristian/OSUCollectionManager).
3. În **Settings → Actions → General** al repo-ului, lasă **Workflow permissions** pe „Read and write” (ca release-ul să poată publica fișiere).
4. Înainte de fiecare release: setezi în `osc_collector/version.py` versiunea dorită (ex. `__version__ = "0.5.0"`).
5. Creezi un tag **identic** cu prefix `v`: `git tag v0.5.0` apoi `git push origin v0.5.0`.
6. Workflow-ul **Release** (`.github/workflows/release.yml`) rulează pe runner Windows: teste .NET, build PyInstaller + publish self-contained, **Inno Setup** (instalat prin Chocolatey), apoi publică un **GitHub Release** cu un singur fișier: **`OSC_<versiune>_Setup.exe`**. Utilizatorul descarcă setup-ul, îl rulează și urmează asistentul (instalare în `%LocalAppData%\Programs\OSC`, fără admin; shortcut în Meniul Start).

### Unde apare pe GitHub (sidebar **Releases**)

În pagina repo-ului, în dreapta, secțiunea **Releases** (cea cu **Create a new release**) este unde stau versiunile publice. **Setup-ul care „îi face tot”** este fișierul **`OSC_x.y.z_Setup.exe`** atașat la acel release.

- **Automat:** nu e nevoie să apeși „Create a new release” pentru build. După `git push origin v0.5.0` (tag-ul trebuie să coincidă cu `version.py`), workflow-ul **Release** din **Actions** compilează aplicația + installerul Inno și **publică singur** un release în aceeași listă **Releases**, cu **`OSC_<versiune>_Setup.exe`**. Prietenul deschide release-ul, dă download la setup, Next → Next → gata (shortcut, folder instalare, fără Python/.NET manual).
- **Manual (din site):** poți folosi **Create a new release**, alegi un tag, încarci **`OSC_x.y.z_Setup.exe`** făcut local (`.\build_exe.ps1` apoi `.\build_installer.ps1`), apoi **Publish release**.

**Dacă vezi doar „N tags” și pare gol la Releases:** pe GitHub, tag ≠ release publicat. Fie aștepți / verifici că workflow-ul **Release** a reușit după push la tag, fie creezi tu release-ul din **Create a new release** și atașezi setup-ul.

Dacă tag-ul nu coincide cu `__version__` din `version.py`, workflow-ul eșuează (evită release-uri greșite).

### Installer local (Inno Setup)

După `.\build_exe.ps1`, cu [Inno Setup 6](https://jrsoftware.org/isdl.php) instalat:

```powershell
.\build_installer.ps1
```

Rezultat: `installer\Output\OSC_<versiune>_Setup.exe`. Versiunea se ia din `version.py` sau `.\build_installer.ps1 -Version 0.5.0`. Poți edita și `installer\OSC_Setup.iss` în Inno Compiler (`/DMyAppVersion=...` pe linia de comandă suprascrie fallback-ul din script).

**Iconiță aplicație:** `assets\OSC.ico` (generat din `logo.png` cu `python tools\generate_osc_icon.py`). PyInstaller (`OSC.spec`) și Inno Setup (`SetupIconFile`) folosesc acest fișier.

**Cum verifici că exe-ul e cel nou:** în bara de titlu trebuie să vezi versiunea din `osc_collector/version.py` și **`build YYYY-MM-DD HH:MM:SS`** (stamp generat de `build_exe.ps1`). În `OSC.spec`, intrarea PyInstaller este `osc_collector/__main__.py`.

Dacă build-ul eșuează cu **Access is denied** la `dist\OSC`: **închide OSC.exe** (și orice Explorer cu folderul deschis). Scriptul construiește întâi în `dist\_osc_build_staging\OSC\`; dacă nu poate muta peste `dist\OSC`, lasă pachetul nou acolo ca să îl copiezi manual.

**Probleme la sidebar (lazer):** vezi secțiunea *Colecții: osu!lazer vs osu!stable*; corectează `%AppData%\OSC\settings.json` sau **Setări** (nu folosi folderul `OSC.exe` / `dist\OSC` ca folder de date osu).

**Collection Manager:** dacă ai [Collection Manager](https://github.com/Piotrekol/CollectionManager) instalat, OSC caută `user.config` sub `%LocalAppData%` în foldere tip `CollectionManager.App.Win`, `CollectionManager.App.WinForms` sau orice nume care conține „CollectionManager”, citește JSON-ul `StartupSettings` / `OsuLocation` și îl folosește ca folder de date implicit dacă folderul salvat în OSC nu arată ca date osu!. CM însuși verifică lazer doar prin `client.realm` literal; OSC acceptă și `client_<N>.realm` (vezi codul sursă `OsuPathResolver` / `StartupPresenter` în repo-ul CM).

## Utilitar C# (OBLIGATORIU pentru lazer)

```powershell
cd tools\OscLazerRealmImport
dotnet publish -c Release -r win-x64 --self-contained true
```

Pentru același layout ca la `build_exe.ps1`, publică cu `-o` într-un folder și copiază tot output-ul lângă `OSC.exe` din `dist\OSC`.

Comenzi:

- `OscLazerRealmImport list <client.realm>` → JSON sumar (nume + număr beatmap-uri).
- `OscLazerRealmImport list-detail <client.realm>` → JSON cu `collections[].items[]`: MD5 + titlu/artist/difficulty din **Beatmap**; **`rank`** (D…SSH, SS) și **`pp`** din cel mai bun scor **osu!** (mod standard) din tabelul **Score**, după `TotalScore` — același principiu ca nota osu! din Collection Manager (legare prin `Beatmap.Hash` / `MD5Hash`). PP poate lipsi până calculează lazerul în fundal.
- `OscLazerRealmImport remove-beatmaps <realm> <guid_colecție> <hashes.txt>` → scoate hash-urile din acea colecție (închide jocul).
- `OscLazerRealmImport <realm> <replace|merge|append> <nume> <hashes.txt>` → import.

Închide **osu!lazer** înainte de **import** (scriere). Comanda **list** folosește deschidere **read-only** și poate funcționa uneori cu jocul pornit.

## Fișiere proiect (rezumat)

| Modul | Rol |
|--------|-----|
| `osc_collector/main_ui.py` | Fereastra principală, sidebar, import |
| `osc_collector/settings_store.py` / `settings_dialog.py` | Persistență + UI setări |
| `osc_collector/library_service.py` | Listare colecții stable / lazer |
| `osc_collector/lazer_realm_import.py` | Apel utilitar C# |
| `tools/OscLazerRealmImport` | Realm **20.x**, acces **dinamic** la `BeatmapCollection` (list + import) |

## Note

Mirror-urile terțe nu sunt serviciul oficial osu!; respectă [termenii](https://osu.ppy.sh/legal/terms) și regulile fiecărui site.

**Mirror .osz:** metadata colecției vine din **osu!Collector** (API public). Poți descărca astfel:

1. **Site oficial (recomandat dacă ai cont osu!)** — în **Setări**, câmpul **Cookie osu.ppy.sh**: același tip de autentificare ca în [Piotrekol Collection Manager](https://github.com/Piotrekol/CollectionManager) (`downloadSources.json`: URL `https://osu.ppy.sh/beatmapsets/{id}/download`, `?noVideo=1`, Referer pe beatmapset). Copiază valoarea header-ului **Cookie** din DevTools când ești logat pe [osu.ppy.sh](https://osu.ppy.sh) (ex. ghid video din CM: [streamable.com/lhlr3d](https://streamable.com/lhlr3d)). Descărcările rulează într-un **pool continuu** (până la **10** fire simultan), cu **câte un client HTTP reutilizabil pe fir** (keep-alive TCP). Nu mai există throttling artificial pe minut (încetinea totul); dacă **osu.ppy.sh** răspunde **403**, setul trece automat la **mirror-uri**. Modul **Automat** folosește **ordinea fixă** Beatconnect → … fără „probă” secvențială la început (economisește timp la start).

2. **Mirror-uri terțe** — dacă cookie-ul e gol, se folosesc doar mirror-urile. Implicit **Beatconnect**; **Catboy** poate da **403**; **Nerinyan** poate întoarce **HTML**. Modul **Automat** le încearcă în lanț.

Respectă termenii osu! și ai fiecărui mirror.

Dacă vezi **getaddrinfo failed** sau **11001**, problema e **DNS / rețea pe PC** (nu rezolvă numele domeniilor), nu lista de hărți. Verifică internet, DNS (ex. 8.8.8.8), VPN, fișierul `hosts`, firewall. OSC oprește descărcarea din timp cu un dialog dacă **niciun** mirror nu e rezolvabil.
