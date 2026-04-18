-- Meal Planner Database Schema
-- PostgreSQL 15

-- Create custom enum type for meal categories
CREATE TYPE meal_type AS ENUM ('breakfast', 'lunch', 'dinner');

-- Meals table: stores all available meal options
CREATE TABLE meals (
  Meal_ID SERIAL PRIMARY KEY,
  Meal_Description TEXT,
  Meal_Type meal_type,
  Effort_Level INT
);

-- Eaters table: the people using the system
CREATE TABLE eaters (
  Eater_ID SERIAL PRIMARY KEY,
  Name TEXT
);

-- Eater meal preferences: many-to-many junction table
-- Maps which eaters like which meals
CREATE TABLE eater_meal_preferences (
  Eater_ID INT,
  Meal_ID INT,
  PRIMARY KEY (Eater_ID, Meal_ID),
  FOREIGN KEY (Eater_ID) REFERENCES eaters(Eater_ID),
  FOREIGN KEY (Meal_ID) REFERENCES meals(Meal_ID)
);

-- Meal schedule: the generated weekly plan
-- Uses upsert (ON CONFLICT DO UPDATE) for re-runnability
CREATE TABLE meal_schedule (
  Date DATE,
  Group_Meal BOOLEAN,
  Meal_Type meal_type,
  Meal_ID INT REFERENCES meals(Meal_ID),
  Eater_ID INT REFERENCES eaters(Eater_ID),
  Eat_Out BOOLEAN,
  PRIMARY KEY (Date, Meal_Type, Eater_ID)
);
