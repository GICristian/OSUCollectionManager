using OscLazerRealmImport.Models;
using Realms;
using Xunit;

namespace OscLazerRealmImport.Tests;

public class TypedRealmRoundtripTests
{
    [Fact]
    public void Write_collection_then_read_same_schema_as_osu()
    {
        var path = Path.Combine(Path.GetTempPath(), $"osc_realm_test_{Guid.NewGuid():N}.realm");
        var syncPrev = SynchronizationContext.Current;
        SynchronizationContext.SetSynchronizationContext(null);
        try
        {
            var cfgWrite = new RealmConfiguration(path)
            {
                SchemaVersion = OscLazerRealmImport.OscRealm.OsuSchemaVersion,
            };

            using (var rw = Realm.GetInstance(cfgWrite))
            {
                rw.Write(() =>
                {
                    var c = new BeatmapCollection
                    {
                        ID = Guid.NewGuid(),
                        Name = "OSC_Test_Collection",
                        LastModified = DateTimeOffset.UtcNow,
                    };
                    c.BeatmapMD5Hashes.Add(new string('a', 32));
                    c.BeatmapMD5Hashes.Add(new string('b', 32));
                    rw.Add(c);
                });
            }

            var cfgRead = new RealmConfiguration(path)
            {
                IsReadOnly = true,
                SchemaVersion = OscLazerRealmImport.OscRealm.OsuSchemaVersion,
            };

            using var ro = Realm.GetInstance(cfgRead);
            var all = ro.All<BeatmapCollection>().ToList();
            Assert.Single(all);
            Assert.Equal("OSC_Test_Collection", all[0].Name);
            Assert.Equal(2, all[0].BeatmapMD5Hashes.Count);
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(syncPrev);
            TryDelete(path);
            TryDelete(path + ".management");
            TryDelete(path + ".lock");
        }
    }

    private static void TryDelete(string p)
    {
        try
        {
            if (File.Exists(p))
                File.Delete(p);
        }
        catch
        {
            // temp cleanup best-effort
        }
    }

}
