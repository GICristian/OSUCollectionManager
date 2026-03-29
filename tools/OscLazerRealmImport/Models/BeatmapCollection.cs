// Aliniat la osu.Game.Collections.BeatmapCollection (ppy/osu) — același layout Realm.

using Realms;

namespace OscLazerRealmImport.Models;

public partial class BeatmapCollection : IRealmObject
{
    [PrimaryKey]
    public Guid ID { get; set; }

    public string Name { get; set; } = string.Empty;

    public IList<string> BeatmapMD5Hashes { get; } = null!;

    public DateTimeOffset LastModified { get; set; }
}
