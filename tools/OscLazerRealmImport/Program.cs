// osu!lazer Realm: import, listare, listă detaliată (beatmap-uri), eliminare hash-uri din colecție.
//
// Comenzi:
//   list <client.realm>
//   list-detail <client.realm>   → JSON cu colecții + items (rezolvare vs tabelul Beatmap)
//   remove-beatmaps <client.realm> <collection_guid> <hashes.txt>
//   <client.realm> <replace|merge|append> <name> <hashes.txt>
//
// IsDynamic: evită validarea schemei C# în read-only. Tabel beatmap în joc: „Beatmap” (MapTo în ppy/osu).

using System.Text.Json;
using OscLazerRealmImport.ListOutput;
using Realms;

int code;
if (args.Length >= 1 && args[0].Equals("list-detail", StringComparison.OrdinalIgnoreCase))
    code = RunListDetail(args);
else if (args.Length >= 1 && args[0].Equals("remove-beatmaps", StringComparison.OrdinalIgnoreCase))
    code = RunRemoveBeatmaps(args);
else if (args.Length >= 1 && args[0].Equals("list", StringComparison.OrdinalIgnoreCase))
    code = RunList(args);
else if (args.Length == 4)
    code = RunImport(args);
else
{
    Console.Error.WriteLine(
        "Usage:\n"
        + "  OscLazerRealmImport list <client.realm>\n"
        + "  OscLazerRealmImport list-detail <client.realm>\n"
        + "  OscLazerRealmImport remove-beatmaps <client.realm> <collection_guid> <hashes.txt>\n"
        + "  OscLazerRealmImport <client.realm> <replace|merge|append> <collection_name> <hashes.txt>");
    code = 1;
}

return code;

static JsonSerializerOptions JsonOut() => new()
{
    WriteIndented = false,
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
};

static int RunList(string[] args)
{
    if (args.Length != 2)
    {
        Console.Error.WriteLine("Usage: OscLazerRealmImport list <client.realm>");
        return 1;
    }

    var realmPath = Path.GetFullPath(args[1]);
    if (!File.Exists(realmPath))
    {
        Console.Error.WriteLine($"Realm file not found: {realmPath}");
        return 1;
    }

    try
    {
        var config = new RealmConfiguration(realmPath)
        {
            IsDynamic = true,
            IsReadOnly = true,
            SchemaVersion = OscLazerRealmImport.OscRealm.OsuSchemaVersion,
        };

        using var realm = Realm.GetInstance(config);
        var rows = new List<(string name, int beatmaps)>();
        foreach (var c in realm.DynamicApi.All("BeatmapCollection"))
        {
            var name = (string)c.DynamicApi.Get<string>("Name");
            var cnt = c.DynamicApi.GetList<string>("BeatmapMD5Hashes").Count;
            rows.Add((name, cnt));
        }

        if (rows.Count == 0)
            EmitEmptyListHint(realm);

        rows.Sort((a, b) => string.Compare(a.name, b.name, StringComparison.OrdinalIgnoreCase));
        var payload = rows.Select(r => new { name = r.name, beatmaps = r.beatmaps }).ToList();
        Console.WriteLine(JsonSerializer.Serialize(payload, JsonOut()));
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        return 1;
    }
}

static int RunListDetail(string[] args)
{
    if (args.Length != 2)
    {
        Console.Error.WriteLine("Usage: OscLazerRealmImport list-detail <client.realm>");
        return 1;
    }

    var realmPath = Path.GetFullPath(args[1]);
    if (!File.Exists(realmPath))
    {
        Console.Error.WriteLine($"Realm file not found: {realmPath}");
        return 1;
    }

    try
    {
        var config = new RealmConfiguration(realmPath)
        {
            IsDynamic = true,
            IsReadOnly = true,
            SchemaVersion = OscLazerRealmImport.OscRealm.OsuSchemaVersion,
        };

        using var realm = Realm.GetInstance(config);
        var byMd5 = new Dictionary<string, (string title, string artist, string difficulty, string beatmapHash)>(
            StringComparer.OrdinalIgnoreCase);

        try
        {
            foreach (var b in realm.DynamicApi.All("Beatmap"))
            {
                var md5 = ((string)b.DynamicApi.Get<string>("MD5Hash")).Trim();
                if (md5.Length == 0)
                    continue;
                md5 = md5.ToLowerInvariant();
                var diff = SafeString(b, "DifficultyName");
                var beatmapHash = SafeString(b, "Hash").Trim();
                string title = "";
                string artist = "";
                try
                {
                    var meta = b.DynamicApi.Get<IRealmObject>("Metadata");
                    if (meta is null)
                    {
                        var setInfo = b.DynamicApi.Get<IRealmObject>("BeatmapSet");
                        if (setInfo is not null)
                            meta = setInfo.DynamicApi.Get<IRealmObject>("Metadata");
                    }
                    if (meta is not null)
                    {
                        title = SafeString(meta, "Title");
                        artist = SafeString(meta, "Artist");
                    }
                }
                catch
                {
                    // fără metadata legată
                }

                byMd5[md5] = (title, artist, diff, beatmapHash);
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(
                "OSC: Avertisment list-detail (scan Beatmap): " + ex.Message
                + " — items vor avea missing=true dacă nu se poate rezolva.");
        }

        var bestByBeatmapHash = new Dictionary<string, (int rank, double? pp, long totalScore)>(
            StringComparer.OrdinalIgnoreCase);
        var bestByMd5 = new Dictionary<string, (int rank, double? pp, long totalScore)>(
            StringComparer.OrdinalIgnoreCase);

        try
        {
            foreach (var s in realm.DynamicApi.All("Score"))
            {
                try
                {
                    if (GetBoolProperty(s, "DeletePending"))
                        continue;
                    var ruleset = s.DynamicApi.Get<IRealmObject>("Ruleset");
                    if (!IsOsuStandardRuleset(ruleset))
                        continue;
                    var rankInt = s.DynamicApi.Get<int>("Rank");
                    var totalScore = s.DynamicApi.Get<long>("TotalScore");
                    var ppVal = TryGetNullableDouble(s, "PP");
                    var bh = SafeString(s, "BeatmapHash").Trim().ToLowerInvariant();
                    if (bh.Length > 0)
                        ConsiderBetterScore(bestByBeatmapHash, bh, rankInt, ppVal, totalScore);
                    var bi = s.DynamicApi.Get<IRealmObject>("BeatmapInfo");
                    if (bi is not null)
                    {
                        var md5FromScore = ((string)bi.DynamicApi.Get<string>("MD5Hash")).Trim().ToLowerInvariant();
                        if (md5FromScore.Length == 32)
                            ConsiderBetterScore(bestByMd5, md5FromScore, rankInt, ppVal, totalScore);
                    }
                }
                catch
                {
                    // înregistrare Score atipică
                }
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("OSC: Avertisment list-detail (scan Score): " + ex.Message);
        }

        var collections = new List<CollectionOut>();
        foreach (var c in realm.DynamicApi.All("BeatmapCollection"))
        {
            var id = c.DynamicApi.Get<Guid>("ID");
            var name = (string)c.DynamicApi.Get<string>("Name");
            var hashList = c.DynamicApi.GetList<string>("BeatmapMD5Hashes");
            var items = new List<BeatmapLine>();
            foreach (var raw in hashList)
            {
                var h = (raw ?? "").Trim().ToLowerInvariant();
                if (h.Length != 32)
                    continue;
                if (byMd5.TryGetValue(h, out var info))
                {
                    var line = new BeatmapLine
                    {
                        md5 = h,
                        title = info.title,
                        artist = info.artist,
                        difficulty = info.difficulty,
                        missing = false,
                    };
                    ApplyLocalOsuScore(line, h, info.beatmapHash, bestByMd5, bestByBeatmapHash);
                    items.Add(line);
                }
                else
                {
                    var line = new BeatmapLine
                    {
                        md5 = h,
                        title = "",
                        artist = "",
                        difficulty = "",
                        missing = true,
                    };
                    ApplyLocalOsuScore(line, h, "", bestByMd5, bestByBeatmapHash);
                    items.Add(line);
                }
            }

            items.Sort((a, b) => string.Compare(
                $"{a.artist}\t{a.title}\t{a.difficulty}",
                $"{b.artist}\t{b.title}\t{b.difficulty}",
                StringComparison.OrdinalIgnoreCase));

            collections.Add(new CollectionOut
            {
                id = id.ToString("D"),
                name = name,
                beatmaps = items.Count,
                items = items,
            });
        }

        collections.Sort((a, b) => string.Compare(a.name, b.name, StringComparison.OrdinalIgnoreCase));

        if (collections.Count == 0)
            EmitEmptyListHint(realm);

        Console.WriteLine(JsonSerializer.Serialize(new ListDetailRoot { collections = collections }, JsonOut()));
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        return 1;
    }
}

static string SafeString(IRealmObject o, string prop)
{
    try
    {
        return (string)o.DynamicApi.Get<string>(prop) ?? "";
    }
    catch
    {
        return "";
    }
}

static bool GetBoolProperty(IRealmObject o, string prop)
{
    try
    {
        return o.DynamicApi.Get<bool>(prop);
    }
    catch
    {
        return false;
    }
}

static bool IsOsuStandardRuleset(IRealmObject? ruleset)
{
    if (ruleset is null)
        return false;
    try
    {
        var onlineId = ruleset.DynamicApi.Get<long>("OnlineID");
        if (onlineId == 0)
            return true;
    }
    catch
    {
        // ignoră
    }

    return SafeString(ruleset, "ShortName").Equals("osu", StringComparison.OrdinalIgnoreCase);
}

static double? TryGetNullableDouble(IRealmObject o, string prop)
{
    try
    {
        return o.DynamicApi.Get<double?>(prop);
    }
    catch
    {
        try
        {
            return o.DynamicApi.Get<double>(prop);
        }
        catch
        {
            return null;
        }
    }
}

static void ConsiderBetterScore(
    Dictionary<string, (int rank, double? pp, long totalScore)> dict,
    string key,
    int rank,
    double? pp,
    long totalScore)
{
    if (string.IsNullOrEmpty(key))
        return;
    if (!dict.TryGetValue(key, out var cur) || totalScore > cur.totalScore)
        dict[key] = (rank, pp, totalScore);
}

/// <summary>MapTo Rank pe ScoreInfo → int ScoreRank (ppy/osu).</summary>
static string FormatRankFromInt(int rankInt) => rankInt switch
{
    -1 => "F",
    0 => "D",
    1 => "C",
    2 => "B",
    3 => "A",
    4 => "S",
    5 => "SH",
    6 => "SS",
    7 => "SSH",
    _ => "",
};

static void ApplyLocalOsuScore(
    BeatmapLine line,
    string md5Lower,
    string beatmapContentHash,
    Dictionary<string, (int rank, double? pp, long totalScore)> bestByMd5,
    Dictionary<string, (int rank, double? pp, long totalScore)> bestByBeatmapHash)
{
    if (bestByMd5.TryGetValue(md5Lower, out var byMd5))
    {
        AssignRankPp(line, byMd5);
        return;
    }

    var hk = beatmapContentHash.Trim().ToLowerInvariant();
    if (hk.Length > 0 && bestByBeatmapHash.TryGetValue(hk, out var byHash))
        AssignRankPp(line, byHash);
}

static void AssignRankPp(BeatmapLine line, (int rank, double? pp, long _) s)
{
    var label = FormatRankFromInt(s.rank);
    if (label.Length > 0)
        line.rank = label;
    line.pp = s.pp;
}

static int RunRemoveBeatmaps(string[] args)
{
    if (args.Length != 4)
    {
        Console.Error.WriteLine(
            "Usage: OscLazerRealmImport remove-beatmaps <client.realm> <collection_guid> <hashes.txt>");
        return 1;
    }

    var realmPath = Path.GetFullPath(args[1]);
    if (!Guid.TryParse(args[2].Trim(), out var collectionId))
    {
        Console.Error.WriteLine("collection_guid must be a valid GUID.");
        return 1;
    }

    var hashesPath = Path.GetFullPath(args[3]);
    if (!File.Exists(realmPath))
    {
        Console.Error.WriteLine($"Realm file not found: {realmPath}");
        return 1;
    }

    if (!File.Exists(hashesPath))
    {
        Console.Error.WriteLine($"Hashes file not found: {hashesPath}");
        return 1;
    }

    var removeSet = new HashSet<string>(
        File.ReadAllLines(hashesPath)
            .Select(l => l.Trim().ToLowerInvariant())
            .Where(l => l.Length == 32
                        && l.All(ch => ch is (>= '0' and <= '9') or (>= 'a' and <= 'f'))),
        StringComparer.Ordinal);

    if (removeSet.Count == 0)
    {
        Console.Error.WriteLine("No valid 32-char hex MD5 lines in hashes file.");
        return 1;
    }

    try
    {
        var config = new RealmConfiguration(realmPath)
        {
            IsDynamic = true,
            SchemaVersion = OscLazerRealmImport.OscRealm.OsuSchemaVersion,
        };

        using var realm = Realm.GetInstance(config);

        realm.Write(() =>
        {
            IRealmObject? target = null;
            foreach (var c in realm.DynamicApi.All("BeatmapCollection"))
            {
                if (c.DynamicApi.Get<Guid>("ID") == collectionId)
                {
                    target = c;
                    break;
                }
            }

            if (target is null)
                throw new InvalidOperationException($"No BeatmapCollection with ID {collectionId:D}.");

            var list = target.DynamicApi.GetList<string>("BeatmapMD5Hashes");
            var keep = new List<string>();
            foreach (var h in list)
            {
                var norm = (h ?? "").Trim().ToLowerInvariant();
                if (!removeSet.Contains(norm) && h is not null)
                    keep.Add(h);
            }

            list.Clear();
            foreach (var h in keep)
                list.Add(h);

            target.DynamicApi.Set("LastModified", DateTimeOffset.UtcNow);
        });

        Console.WriteLine($"OK: removed {removeSet.Count} hash(es) from collection (remaining rows updated).");
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        PrintImportHints(ex);
        return 1;
    }
}

static void PrintImportHints(Exception ex)
{
    var hint = ex.Message;
    if (ex.InnerException is { } inner)
        hint += " " + inner.Message;

    if (hint.Contains("lock", StringComparison.OrdinalIgnoreCase)
        || hint.Contains("being used", StringComparison.OrdinalIgnoreCase)
        || hint.Contains("cannot access", StringComparison.OrdinalIgnoreCase)
        || hint.Contains("another process", StringComparison.OrdinalIgnoreCase))
    {
        Console.Error.WriteLine(
            "Tip: închide osu!lazer, deschide Task Manager și termină orice proces „osu!” / „osu!lazer”, apoi încearcă din nou.");
    }
    else if (hint.Contains("unsupported version", StringComparison.OrdinalIgnoreCase)
             && hint.Contains("cannot be upgraded", StringComparison.OrdinalIgnoreCase))
    {
        Console.Error.WriteLine(
            "Tip: recompilează OscLazerRealmImport (dotnet publish) — pachetul Realm trebuie să fie la zi.");
    }
    else if (hint.Contains("schema", StringComparison.OrdinalIgnoreCase)
             || (hint.Contains("realm", StringComparison.OrdinalIgnoreCase)
                 && !hint.Contains("unsupported version", StringComparison.OrdinalIgnoreCase)))
    {
        Console.Error.WriteLine(
            "Tip: folosește client_<număr>.realm din %AppData%\\osu\\.");
    }
}

static int RunImport(string[] args)
{
    var realmPath = Path.GetFullPath(args[0]);
    var mode = args[1].Trim().ToLowerInvariant();
    var collectionName = args[2];
    var hashesPath = Path.GetFullPath(args[3]);

    if (!File.Exists(realmPath))
    {
        Console.Error.WriteLine($"Realm file not found: {realmPath}");
        return 1;
    }

    if (mode is not ("replace" or "merge" or "append"))
    {
        Console.Error.WriteLine("Mode must be replace, merge, or append.");
        return 1;
    }

    if (!File.Exists(hashesPath))
    {
        Console.Error.WriteLine($"Hashes file not found: {hashesPath}");
        return 1;
    }

    var hashes = File.ReadAllLines(hashesPath)
        .Select(l => l.Trim().ToLowerInvariant())
        .Where(l => l.Length == 32
                    && l.All(c => c is (>= '0' and <= '9') or (>= 'a' and <= 'f')))
        .Distinct()
        .ToList();

    if (hashes.Count == 0)
    {
        Console.Error.WriteLine("No valid 32-char hex MD5 lines in hashes file.");
        return 1;
    }

    try
    {
        var config = new RealmConfiguration(realmPath)
        {
            IsDynamic = true,
            SchemaVersion = OscLazerRealmImport.OscRealm.OsuSchemaVersion,
        };

        using var realm = Realm.GetInstance(config);

        realm.Write(() =>
        {
            var all = new List<IRealmObject>();
            foreach (var c in realm.DynamicApi.All("BeatmapCollection"))
                all.Add(c);

            if (mode == "replace")
            {
                foreach (var c in all)
                {
                    if (NameEquals(c, collectionName))
                        realm.Remove(c);
                }

                CreateCollection(realm, collectionName, hashes);
                return;
            }

            if (mode == "merge")
            {
                var existing = FindByName(all, collectionName);
                if (existing is null)
                {
                    CreateCollection(realm, collectionName, hashes);
                    return;
                }

                var list = existing.DynamicApi.GetList<string>("BeatmapMD5Hashes");
                var have = new HashSet<string>(list);
                foreach (var h in hashes)
                {
                    if (have.Add(h))
                        list.Add(h);
                }

                existing.DynamicApi.Set("LastModified", DateTimeOffset.UtcNow);
                return;
            }

            var finalName = PickAppendName(all, collectionName);
            CreateCollection(realm, finalName, hashes);
        });

        Console.WriteLine($"OK: {hashes.Count} beatmap hash(es) written.");
        return 0;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.ToString());
        PrintImportHints(ex);
        return 1;
    }
}

static bool NameEquals(IRealmObject c, string name) =>
    string.Equals((string)c.DynamicApi.Get<string>("Name"), name, StringComparison.Ordinal);

static IRealmObject? FindByName(List<IRealmObject> all, string name)
{
    foreach (var c in all)
    {
        if (NameEquals(c, name))
            return c;
    }

    return null;
}

static string PickAppendName(List<IRealmObject> all, string baseName)
{
    var names = new HashSet<string>(StringComparer.Ordinal);
    foreach (var c in all)
        names.Add((string)c.DynamicApi.Get<string>("Name"));

    if (!names.Contains(baseName))
        return baseName;
    var i = 2;
    while (names.Contains($"{baseName} ({i})"))
        i++;
    return $"{baseName} ({i})";
}

static void EmitEmptyListHint(Realm realm)
{
    try
    {
        var names = realm.Schema.Select(s => s.Name).OrderBy(n => n).ToList();
        bool hasCollection = names.Any(n =>
            string.Equals(n, "BeatmapCollection", StringComparison.Ordinal));

        if (!hasCollection)
        {
            Console.Error.WriteLine(
                "OSC: În acest fișier Realm nu există tipul BeatmapCollection (altă versiune de joc / fișier greșit?). "
                + "Tipuri în schema: "
                + (names.Count == 0 ? "(niciunul)" : string.Join(", ", names)));
        }
        else
        {
            Console.Error.WriteLine(
                "OSC: BeatmapCollection există dar nu are înregistrări. "
                + "Asigură-te că folderul din OSC = folderul din osu!lazer (Setări → Conținut), "
                + "și că deschizi client_*.realm / client.realm din acel folder, nu o copie veche.");
        }
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine("OSC (diagnostic listă goală): " + ex.Message);
    }
}

static void CreateCollection(Realm realm, string name, List<string> hashes)
{
    var id = Guid.NewGuid();
    var obj = realm.DynamicApi.CreateObject("BeatmapCollection", id);
    obj.DynamicApi.Set("Name", name);
    obj.DynamicApi.Set("LastModified", DateTimeOffset.UtcNow);
    var list = obj.DynamicApi.GetList<string>("BeatmapMD5Hashes");
    foreach (var h in hashes)
        list.Add(h);
}
