using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using Logic;

namespace URAH
{
    /// <summary>
    /// Ties a plugin's Harmony patches to the game's mod list: they are applied while an active mod
    /// names the plugin's GUID in its bepinex_plugins.txt (root folder of the mod, one GUID per line)
    /// and removed when the last such mod is switched off. The file sits outside defs/maps/texts, so
    /// it stays out of the mod checksum.
    ///
    /// ModManager.OnActiveModsChanged fires on every toggle in the Mods menu and from LoadModList,
    /// which Defs.Load runs before the defs are read, so the patches are in place before the mod's data
    /// loads. The ModManager is created after the plugins (UserSettings, active_mod), so a postfix on its
    /// constructor subscribes. ModManager has only plain static fields; patching it at plugin load is safe
    /// (unlike UserSettings, see URAH_Zoom).
    ///
    /// Mono cannot unload an assembly: a switched-off plugin stays loaded, only unpatched. Whatever it
    /// changed outside its patches has to be put back by the plugin (Changed) or waits for a restart.
    /// </summary>
    internal sealed class ModLink
    {
        public const string FileName = "bepinex_plugins.txt";

        private static readonly List<ModLink> links = new List<ModLink>();
        private static ModManager subscribed;

        private readonly string guid;
        private readonly Assembly assembly;
        private readonly ManualLogSource log;
        private readonly Harmony harmony;

        /// <summary>The plugin's patches are applied: an active mod asks for it.</summary>
        public bool Active { get; private set; }

        /// <summary>Raised after the patches were applied (true) or removed (false).</summary>
        public event Action<bool> Changed;

        public ModLink(string guid, Assembly assembly, ManualLogSource log)
        {
            this.guid = guid;
            this.assembly = assembly;
            this.log = log;
            harmony = new Harmony(guid);
            links.Add(this);
            if (links.Count == 1)
            {
                new Harmony(guid + ".modlink").Patch(AccessTools.Constructor(typeof(ModManager)),
                    postfix: new HarmonyMethod(typeof(ModLink), nameof(ModManagerCtorPostfix)));
            }
            Subscribe(AccessTools.Field(typeof(ModManager), "_instance").GetValue(null) as ModManager);
        }

        private static void ModManagerCtorPostfix(ModManager __instance) => Subscribe(__instance);

        private static void Subscribe(ModManager manager)
        {
            if (manager == null || manager == subscribed)
            {
                return;
            }
            subscribed = manager;
            manager.OnActiveModsChanged += SyncAll;
            SyncAll();
        }

        private static void SyncAll()
        {
            foreach (ModLink link in links)
            {
                link.Sync();
            }
        }

        private void Sync()
        {
            Mod by = FindRequestingMod();
            if ((by != null) == Active)
            {
                return;
            }
            try
            {
                if (by != null)
                {
                    harmony.PatchAll(assembly);
                }
                else
                {
                    harmony.UnpatchSelf();
                }
            }
            catch (Exception e)
            {
                log.LogError($"{(by != null ? "Patching" : "Unpatching")} failed: {e}");
                harmony.UnpatchSelf();
                Active = false;
                return;
            }
            Active = by != null;
            log.LogInfo(Active ? $"Enabled by mod {by.DisplayName}" : "Disabled: no active mod uses it");
            try
            {
                Changed?.Invoke(Active);
            }
            catch (Exception e)
            {
                log.LogError($"Mod link handler failed: {e}");
            }
        }

        private Mod FindRequestingMod()
        {
            List<Mod> mods = subscribed?.GetActiveMods();
            if (mods == null)
            {
                return null;
            }
            foreach (Mod mod in mods)
            {
                try
                {
                    string path = mod.base_path + FileName;
                    if (File.Exists(path) &&
                        File.ReadAllLines(path).Any(l => l.Trim().Equals(guid, StringComparison.OrdinalIgnoreCase)))
                    {
                        return mod;
                    }
                }
                catch (Exception e)
                {
                    log.LogWarning($"Reading {FileName} of {mod.DisplayName} failed: {e.Message}");
                }
            }
            return null;
        }
    }
}
