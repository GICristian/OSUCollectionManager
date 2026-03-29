using System;
using Realms;
using System.Linq;

class Program
{
    static void Main(string[] args)
    {
        var realmPath = args[0];
        try {
            var config = new RealmConfiguration(realmPath)
            {
                IsDynamic = true,
                IsReadOnly = true,
                SchemaVersion = 44
            };
            using var realm = Realm.GetInstance(config);
            var names = realm.Schema.Select(s => s.Name).OrderBy(n => n).ToList();
            Console.WriteLine("Tables in Realm: " + string.Join(", ", names));
        } catch(Exception ex) { Console.WriteLine("Error: " + ex); }
    }
}
