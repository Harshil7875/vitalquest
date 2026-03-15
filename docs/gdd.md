## Game Design Document (GDD): VitalQuest

**Project:** VitalQuest

**Version:** 1.8.0

**Focus:** Core Loop, Economy Balancing, Progression, and Social Mechanics

### 1. The Core Gameplay Loop

The fundamental engine of VitalQuest relies on converting real-world friction (managing a chronic illness) into digital dopamine.

1. **Action (Real World):** The user performs a verified health action (e.g., Apple Watch logs 5,000 steps, Dexcom API logs a stable fasting glucose reading, Smart Pillbox logs morning medication).
2. **Reward (Digital):** The secure backend translates this into "Mana" (the primary currency) and occasional crafting materials (e.g., Wood, Stone).
3. **Progression:** The user spends Mana and materials to upgrade their Avatar or expand their virtual town, "The Sanctuary."
4. **Social Validation:** Upgraded stats contribute to the Guild’s collective "Damage" against weekly World Bosses, earning group rewards and social recognition.

### 2. The In-Game Economy: Sources and Sinks

To prevent inflation (where players have so much Mana it becomes worthless) or deflation (where things cost too much and players quit), the economy must be strictly balanced using "Sources" (how currency is earned) and "Sinks" (how it is spent).

**Primary Currency:** Mana

**Premium Currency:** Astral Gems (used for cosmetics, earned rarely in-game or bought with fiat currency).

| Economy Flow | Mechanisms | Balancing Logic |
| --- | --- | --- |
| **Sources (Earning)** | Daily Medication Log (+100 Mana)<br>

<br>Hitting Step Goal (+50 Mana)<br>

<br>Diet Logging (+25 Mana) | Capped at a maximum of 300 Mana per day via the `anti_cheat.py` engine to prevent obsessive or dangerous over-exertion. |
| **Sinks (Spending)** | Sanctuary Upgrades (e.g., 500 Mana)<br>

<br>Avatar Gear Crafting (e.g., 200 Mana)<br>

<br>Guild Buffs (e.g., 100 Mana) | Costs scale exponentially. Level 1 Sanctuary costs 500 Mana; Level 10 costs 50,000 Mana. This requires long-term health consistency. |

### 3. Progression Systems

Progression in VitalQuest is dual-layered to appeal to different gamer archetypes (the "Builder" and the "Fighter").

* **The Sanctuary (Base Building):** Players start with a barren plot of land. By consistently managing their health, they build structures like the *Apothecary* (generates passive crafting materials) or the *Scout Tower* (unlocks new weekly quests). Building takes real-world time, incentivizing daily check-ins.
* **The Avatar (RPG Stats):** Players do not have "Health" or "Strength" stats that map to their real bodies (which could be discouraging). Instead, they level up purely fantasy stats: *Magic, Defense, and Agility*. These stats dictate how much multiplier damage their daily adherence contributes to the Guild Boss.

### 4. Asynchronous Social Mechanics (The Guild Engine)

Direct PvP (Player vs. Player) is explicitly excluded from the design to prevent toxic comparisons of medical conditions. All social mechanics are cooperative (PvE - Player vs. Environment).

* **World Boss Raids:** Every Wednesday, a new World Boss spawns (e.g., "The Lethargy Golem"). The boss has 100,000 HP.
* **Collective Damage:** The Guild’s total daily Mana earned is converted into DPS (Damage Per Second). If the 50 guild members take their meds and hit their step goals, the boss takes massive damage. If adherence drops, the boss survives the week, and the guild misses out on the "Epic Loot Chest" drop.
* **Guild Roles:** The Guildmaster can activate "Rally Flags," sending a secure, non-medical push notification to the guild: *"We are 5,000 damage away from defeating the Golem! Let's get our steps in today!"*

### 5. Ethical Monetization Strategy

Monetizing a health-driven game requires strict ethical boundaries. VitalQuest employs a hybrid model that avoids "Pay-to-Win" (P2W) mechanics entirely. You cannot buy better health tracking or artificially inflate your guild's raid damage with a credit card.

* **Freemium Layer:** The game is 100% free to play. Free users can watch optional, rewarded video ads (e.g., a 30-second ad for a healthy meal delivery service) to instantly finish a Sanctuary building timer.
* **Cosmetic IAP (In-App Purchases):** Players can buy *Astral Gems* to purchase premium Avatar skins, unique pets, or seasonal Sanctuary decorations. These offer zero gameplay advantage.
* **VitalQuest Pro Subscription ($9.99/mo):** This unlocks the "Clinical Dashboard" features. Pro users get AI-driven trend analysis of their API data, exportable PDF reports for their endocrinologist, and an exclusive monthly cosmetic item.

---
