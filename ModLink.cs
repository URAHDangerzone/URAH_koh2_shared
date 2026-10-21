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
    ///
    /// Multiplayer guard: the game's start check compares the players' mod lists and client versions,
    /// not their plugins. A player with the mod but without a working plugin would join and run the mod's
    /// data without its patches. So every active link publishes its plugin version as the player var
    /// urah_p_&lt;guid&gt; (NonPersistentPlayerData, synced to everyone in the lobby, like mod_id) when
    /// entering a lobby, and Campaign.ValidateSetup fails with client_version_mismatch while a player
    /// online has another value. Both patches stay applied while the plugin is switched off; they only act
    /// for active links.
    /// </summary>
    internal sealed class ModLink
    {
        public const string FileName = "bepinex_plugins.txt";
        private const string VarPrefix = "urah_p_";

        private static readonly List<ModLink> links = new List<ModLink>();
        private static ModManager subscribed;

        private readonly string guid;
        private readonly Assembly assembly;
        private readonly ManualLogSource log;
        private readonly Harmony harmony;
        private readonly string version;
        private readonly string varKey;
        private string lastProblem;

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
            version = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
                ?? assembly.GetName().Version.ToString();
            varKey = VarPrefix + guid.Replace('.', '_'); // a dot would be a path in Vars
            links.Add(this);
            if (links.Count == 1)
            {
                Harmony own = new Harmony(guid + ".modlink");
                own.Patch(AccessTools.Constructor(typeof(ModManager)),
                    postfix: new HarmonyMethod(typeof(ModLink), nameof(ModManagerCtorPostfix)));
                own.Patch(AccessTools.Method(typeof(MPBoss), nameof(MPBoss.EnterLobby)),
                    prefix: new HarmonyMethod(typeof(ModLink), nameof(EnterLobbyPrefix)));
                own.Patch(AccessTools.Method(typeof(Campaign), nameof(Campaign.ValidateSetup)),
                    postfix: new HarmonyMethod(typeof(ModLink), nameof(ValidateSetupPostfix)));
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
            PublishInLobby();
            try
            {
                Changed?.Invoke(Active);
            }
            catch (Exception e)
            {
                log.LogError($"Mod link handler failed: {e}");
            }
        }

        // a prefix: EnterLobby sets its own vars unsent and sends them all with the runtime state at the end
        private static void EnterLobbyPrefix(Campaign campaign)
        {
            if (campaign == null)
            {
                return;
            }
            foreach (ModLink link in links)
            {
                link.Publish(campaign, false);
            }
        }

        /// <summary>The mod was toggled while in a lobby: tell the others at once.</summary>
        private void PublishInLobby()
        {
            Campaign campaign = MPBoss.Get()?.game?.campaign;
            if (campaign != null && campaign.IsMultiplayerCampaign() &&
                campaign.GetLocalPlayerRuntimeState() == Campaign.RuntimeState.Lobby)
            {
                Publish(campaign, true);
            }
        }

        private void Publish(Campaign campaign, bool send)
        {
            try
            {
                // inactive: empty instead of the old version, so a host still sees the mismatch
                campaign.SetLocalPlayerVar(RemoteVars.DataType.NonPersistentPlayerData, varKey,
                    Active ? version : "", send);
            }
            catch (Exception e)
            {
                log.LogError($"Publishing the plugin marker failed: {e}");
            }
        }

        private static void ValidateSetupPostfix(Campaign __instance, ref string __result)
        {
            if (__result != null || !__instance.IsMultiplayerCampaign())
            {
                return;
            }
            foreach (ModLink link in links)
            {
                if (link.Active && !link.AllPlayersMatch(__instance))
                {
                    __result = "client_version_mismatch";
                    return;
                }
            }
        }

        /// <summary>Every player online (as the game's own mod_id check counts them) runs this plugin version.</summary>
        private bool AllPlayersMatch(Campaign campaign)
        {
            try
            {
                for (int i = 0; i < 6; i++)
                {
                    string player = campaign.GetPlayerID(i);
                    if (string.IsNullOrEmpty(player) ||
                        campaign.GetPlayerRuntimeState(player) <= Campaign.RuntimeState.Offline)
                    {
                        continue;
                    }
                    string theirs = campaign.GetVar(RemoteVars.DataType.NonPersistentPlayerData, player, varKey).String();
                    if (theirs != version)
                    {
                        // the lobby calls ValidateSetup on every UI refresh: log each state once
                        string problem = $"{campaign.GetPlayerName(player)} has {(string.IsNullOrEmpty(theirs) ? "no active plugin" : "version " + theirs)}, this machine {version}";
                        if (problem != lastProblem)
                        {
                            lastProblem = problem;
                            log.LogWarning($"Multiplayer start blocked: {problem}");
                        }
                        return false;
                    }
                }
            }
            catch (Exception e)
            {
                log.LogError($"Checking the players' plugins failed: {e}");
            }
            lastProblem = null;
            return true;
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
