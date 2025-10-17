#!/usr/bin/env python3
"""
ML анализатор дропа из подарков
Простые модели для предсказания вероятностей
"""

import json
import numpy as np
from collections import defaultdict
from datetime import datetime

class DropAnalyzer:
    """Анализатор вероятностей дропа с помощью ML"""
    
    def __init__(self, stats_file="drop_statistics.json"):
        self.stats_file = stats_file
        self.data = self.load_statistics()
    
    def load_statistics(self):
        """Загрузка статистики"""
        try:
            with open(self.stats_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {"sessions": []}
    
    def get_total_stats(self):
        """Получить агрегированную статистику"""
        if not self.data.get("sessions"):
            return None
        
        total_gifts = 0
        total_items = defaultdict(int)
        
        for session in self.data["sessions"]:
            total_gifts += session["total_opened"]
            for item, count in session["loot"].items():
                total_items[item] += count
        
        return {
            "total_gifts": total_gifts,
            "total_items": dict(total_items),
            "sessions_count": len(self.data["sessions"])
        }
    
    def get_last_session_stats(self):
        """Получить статистику только последней сессии"""
        if not self.data.get("sessions"):
            return None
        
        last_session = self.data["sessions"][-1]
        
        return {
            "total_gifts": last_session["total_opened"],
            "total_items": dict(last_session["loot"]),
            "sessions_count": 1,
            "timestamp": last_session.get("timestamp", "")
        }
    
    def calculate_probabilities(self, stats=None):
        """Вычисление вероятностей дропа каждого предмета"""
        if stats is None:
            stats = self.get_total_stats()
        
        if not stats:
            return None
        
        total_gifts = stats["total_gifts"]
        probabilities = {}
        
        for item, count in stats["total_items"].items():
            probabilities[item] = {
                "count": count,
                "probability": (count / total_gifts) * 100,
                "per_gift": count / total_gifts,
                "rarity": self._calculate_rarity(count, total_gifts)
            }
        
        return probabilities
    
    def _calculate_rarity(self, count, total_gifts):
        """Определение редкости предмета"""
        probability = (count / total_gifts) * 100
        
        if probability >= 50:
            return "legendary"  # Легендарный (выпадает почти всегда)
        elif probability >= 20:
            return "epic"  # Эпический (часто)
        elif probability >= 10:
            return "rare"  # Редкий (средне)
        elif probability >= 5:
            return "uncommon"  # Необычный
        else:
            return "common"  # Обычный (редко)
    
    def predict_next_opening(self, n_gifts=100, stats=None):
        """
        Предсказание ожидаемого дропа при открытии N подарков
        Использует байесовский подход
        """
        probs = self.calculate_probabilities(stats)
        if not probs:
            return None
        
        predictions = {}
        for item, data in probs.items():
            expected_count = data['per_gift'] * n_gifts
            
            # Доверительный интервал (упрощенный)
            std_dev = np.sqrt(n_gifts * data['per_gift'] * (1 - data['per_gift']))
            confidence_low = max(0, expected_count - 1.96 * std_dev)
            confidence_high = expected_count + 1.96 * std_dev
            
            predictions[item] = {
                "expected": round(expected_count, 2),
                "min_95": round(confidence_low, 2),
                "max_95": round(confidence_high, 2),
                "probability": data['probability']
            }
        
        return predictions
    
    def find_best_drops(self, item_types=None):
        """Найти лучшие подарки для получения определенных предметов"""
        probs = self.calculate_probabilities()
        if not probs:
            return None
        
        # Если не указаны типы, берем самые редкие
        if not item_types:
            sorted_by_rarity = sorted(
                probs.items(),
                key=lambda x: x[1]['probability']
            )
            item_types = [item[0] for item in sorted_by_rarity[:5]]
        
        recommendations = {}
        for item in item_types:
            if item in probs:
                data = probs[item]
                recommendations[item] = {
                    "probability": data['probability'],
                    "expected_gifts_needed": int(1 / data['per_gift']) if data['per_gift'] > 0 else 999,
                    "rarity": data['rarity']
                }
        
        return recommendations
    
    def compare_sessions(self):
        """Сравнение разных сессий открытия"""
        if len(self.data["sessions"]) < 2:
            return None
        
        comparison = []
        for session in self.data["sessions"][-5:]:  # Последние 5 сессий
            total_items = sum(session["loot"].values())
            unique_items = len(session["loot"])
            
            comparison.append({
                "timestamp": session["timestamp"],
                "opened": session["total_opened"],
                "total_items": total_items,
                "unique_items": unique_items,
                "avg_items_per_gift": total_items / session["total_opened"] if session["total_opened"] > 0 else 0
            })
        
        return comparison
    
    def get_drop_trends(self):
        """Анализ трендов дропа (улучшается или ухудшается со временем)"""
        if len(self.data["sessions"]) < 3:
            return None
        
        # Группируем по предметам
        item_trends = defaultdict(list)
        
        for session in self.data["sessions"]:
            total_gifts = session["total_opened"]
            for item, count in session["loot"].items():
                prob = (count / total_gifts) * 100 if total_gifts > 0 else 0
                item_trends[item].append(prob)
        
        # Определяем тренды
        trends = {}
        for item, probs in item_trends.items():
            if len(probs) >= 3:
                # Простая линейная регрессия (наклон)
                x = np.arange(len(probs))
                slope = np.polyfit(x, probs, 1)[0]
                
                if slope > 0.5:
                    trend = "растет"
                elif slope < -0.5:
                    trend = "падает"
                else:
                    trend = "стабильно"
                
                trends[item] = {
                    "trend": trend,
                    "slope": round(slope, 2),
                    "recent_prob": round(probs[-1], 2),
                    "avg_prob": round(np.mean(probs), 2)
                }
        
        return trends

# ============================================================================
# ТЕСТИРОВАНИЕ
# ============================================================================

if __name__ == "__main__":
    # Пример использования
    analyzer = DropAnalyzer()
    
    print("=" * 60)
    print("ML АНАЛИЗ ДРОПА")
    print("=" * 60)
    
    # Общая статистика
    stats = analyzer.get_total_stats()
    if stats:
        print(f"\n📊 Всего открыто подарков: {stats['total_gifts']}")
        print(f"📈 Сессий: {stats['sessions_count']}\n")
    
    # Вероятности
    probs = analyzer.calculate_probabilities()
    if probs:
        print("\n🎲 ТОП-10 ПРЕДМЕТОВ ПО ВЕРОЯТНОСТИ:\n")
        sorted_probs = sorted(probs.items(), key=lambda x: x[1]['probability'], reverse=True)
        
        for item, data in sorted_probs[:10]:
            print(f"  {item}: {data['probability']:.2f}% (выпало {data['count']} раз)")
    
    # Предсказание
    predictions = analyzer.predict_next_opening(100)
    if predictions:
        print("\n🔮 ПРЕДСКАЗАНИЕ НА 100 ПОДАРКОВ:\n")
        sorted_pred = sorted(predictions.items(), key=lambda x: x[1]['expected'], reverse=True)
        
        for item, data in sorted_pred[:5]:
            print(f"  {item}: ожидается {data['expected']:.1f} (95% CI: {data['min_95']:.1f}-{data['max_95']:.1f})")
    
    # Тренды
    trends = analyzer.get_drop_trends()
    if trends:
        print("\n📈 ТРЕНДЫ (последние сессии):\n")
        for item, data in list(trends.items())[:5]:
            emoji = "📈" if data['trend'] == "растет" else "📉" if data['trend'] == "падает" else "➡️"
            print(f"  {emoji} {item}: {data['trend']} ({data['recent_prob']:.1f}%)")

