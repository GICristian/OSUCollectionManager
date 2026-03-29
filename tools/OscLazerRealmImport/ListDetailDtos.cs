// DTO-uri JSON pentru comanda list-detail (fără anonymous types / dynamic).

namespace OscLazerRealmImport.ListOutput;

internal sealed class BeatmapLine
{
    public string md5 { get; set; } = "";

    public string title { get; set; } = "";

    public string artist { get; set; } = "";

    public string difficulty { get; set; } = "";

    public bool missing { get; set; }

    /// <summary>Grad pentru modul osu! (ex. SS, S, A); gol dacă nu există scor local.</summary>
    public string rank { get; set; } = "";

    /// <summary>PP al celui mai bun scor osu! (după TotalScore), dacă e calculat.</summary>
    public double? pp { get; set; }
}

internal sealed class CollectionOut
{
    public string id { get; set; } = "";

    public string name { get; set; } = "";

    public int beatmaps { get; set; }

    public List<BeatmapLine> items { get; set; } = new();
}

internal sealed class ListDetailRoot
{
    public List<CollectionOut> collections { get; set; } = new();
}
