"""Quick meals from the dashboard modal, with a meal-type picker."""
from app.extensions import db
from app.models import MealEntry, SavedMeal

from .base import AppTestCase


class QuickMealsTest(AppTestCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            db.session.add_all([
                SavedMeal(user_id=self.user_id, name="Oatmeal bowl",
                          meal_type="breakfast", calories=350, protein_g=20),
                SavedMeal(user_id=self.user_id, name="Vodka martini",
                          meal_type="alcohol", calories=160),
            ])
            db.session.commit()
            self.oatmeal_id = SavedMeal.query.filter_by(name="Oatmeal bowl").one().id

    def test_dashboard_modal_lists_saved_meals_not_drinks_in_quick_tab(self):
        html = self.client.get("/").get_data(as_text=True)
        start = html.index('id="quick-tab-pane"')
        end = html.index('id="drinks-tab-pane"')
        quick = html[start:end]
        self.assertIn("Oatmeal bowl", quick)
        self.assertNotIn("Vodka martini", quick)
        self.assertIn(f"/meals/quick/{self.oatmeal_id}", quick)
        self.assertIn("quick-meal-type-select", quick)
        self.assertIn('name="meal_type" class="quick-meal-type"', quick)

    def test_dashboard_drinks_tab_still_has_no_meal_type_field(self):
        html = self.client.get("/").get_data(as_text=True)
        drinks = html[html.index('id="drinks-tab-pane"'):]
        drinks = drinks[:drinks.index("</form>")]
        self.assertNotIn('class="quick-meal-type"', drinks)

    def test_meals_page_has_meal_type_picker(self):
        html = self.client.get("/meals/").get_data(as_text=True)
        self.assertIn("quick-meal-type-select", html)

    def test_chosen_meal_type_overrides_saved_type(self):
        r = self.client.post(f"/meals/quick/{self.oatmeal_id}",
                             data={"meal_type": "snack", "next": "/"})
        self.assertEqual(r.headers["Location"], "/")
        with self.app.app_context():
            meal = MealEntry.query.one()
            self.assertEqual(meal.meal_type, "snack")
            self.assertEqual(meal.status, "confirmed")
            self.assertEqual(meal.calories, 350)
