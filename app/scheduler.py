"""Meal selection retains explicit preference-list eligibility."""

import random


def eligible_meals(conn, eater_ids, meal_type, excluded, max_effort=None, theme="", required_id=None):
    if not eater_ids:
        return []
    placeholders = ", ".join("?" for _ in eater_ids)
    candidates = conn.execute(
        f"""SELECT m.meal_id FROM meals m
            JOIN eater_meal_preferences p USING (meal_id)
            WHERE m.active=1 AND m.meal_type=? AND p.eater_id IN ({placeholders})
              AND (? IS NULL OR m.effort_level<=?)
              AND (?='' OR lower(m.theme)=?)
              AND (? IS NULL OR m.meal_id=?)
            GROUP BY m.meal_id HAVING count(*)=?
            ORDER BY m.meal_id""",
        [meal_type, *eater_ids, max_effort, max_effort, theme.casefold(), theme.casefold(), required_id, required_id, len(eater_ids)],
    )
    return [row[0] for row in candidates if row[0] not in excluded]


def choose_meal(conn, eater_ids, meal_type, excluded, max_effort=None, theme="", required_id=None):
    eligible = eligible_meals(conn, eater_ids, meal_type, excluded, max_effort, theme, required_id)
    return random.choice(eligible) if eligible else None


def distinct_dinners(options):
    """Maximum matching avoids using Tuesday's only option on an unconstrained Monday."""
    choices = {}
    owner = {}
    shuffled = {}
    for key, meals in options.items():
        shuffled[key] = list(meals)
        random.shuffle(shuffled[key])

    def place(key, visited):
        for meal_id in shuffled[key]:
            if meal_id in visited:
                continue
            visited.add(meal_id)
            if meal_id not in owner or place(owner[meal_id], visited):
                owner[meal_id] = key
                choices[key] = meal_id
                return True
        return False

    for key in sorted(options, key=lambda item: len(options[item])):
        place(key, set())
    return choices
