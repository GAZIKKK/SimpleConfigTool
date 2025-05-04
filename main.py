import json
import os
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom  # Добавляем для форматирования
from collections import defaultdict

# Папка для выходных файлов
OUTPUT_DIR = "out"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Папка для входных файлов
INPUT_DIR = "input"


class ClassInfo:
    """Класс для хранения информации о классе из XML."""
    def __init__(self, name, is_root, documentation):
        self.name = name
        self.is_root = is_root
        self.documentation = documentation
        self.attributes = []
        self.children = []
        self.min = "0"
        self.max = "0"


class Attribute:
    """Класс для хранения информации об атрибуте класса."""
    def __init__(self, name, attr_type):
        self.name = name
        self.type = attr_type


class ModelParser:
    """Парсер для XML-файла."""
    def __init__(self, xml_path):
        self.classes = {}
        self.aggregations = []
        self.parse_xml(xml_path)

    def parse_xml(self, xml_path):
        tree = ET.parse(xml_path)  # Читаю XML-файл
        root = tree.getroot()

        # Парсинг классов
        for class_elem in root.findall(".//Class"):
            name = class_elem.get("name")
            is_root = class_elem.get("isRoot") == "true"
            documentation = class_elem.get("documentation", "")
            class_info = ClassInfo(name, is_root, documentation)

            # Парсинг атрибутов
            for attr_elem in class_elem.findall("Attribute"):
                attr_name = attr_elem.get("name")
                attr_type = attr_elem.get("type")
                class_info.attributes.append(Attribute(attr_name, attr_type))

            self.classes[name] = class_info

        # Парсинг агрегаций
        for agg_elem in root.findall(".//Aggregation"):
            source = agg_elem.get("source")
            target = agg_elem.get("target")
            source_multiplicity = agg_elem.get("sourceMultiplicity")
            target_multiplicity = agg_elem.get("targetMultiplicity")
            self.aggregations.append({
                "source": source,
                "target": target,
                "sourceMultiplicity": source_multiplicity,
                "targetMultiplicity": target_multiplicity
            })
        # Установка min/max и связей
        for agg in self.aggregations:
            source_class = self.classes[agg["source"]]
            target_class = self.classes[agg["target"]]
            target_class.children.append(source_class)

            # Обработка multiplicity
            multiplicity = agg["sourceMultiplicity"]
            if ".." in multiplicity:
                min_val, max_val = multiplicity.split("..")
            else:
                min_val = max_val = multiplicity
            source_class.min = min_val
            source_class.max = max_val

    def get_root_class(self):
        return next(cls for cls in self.classes.values() if cls.is_root)  # Находжу первый корневой класс


class ConfigXMLGenerator:
    """Генератор XML-файла на основе иерархии классов."""
    @staticmethod
    def generate(class_info):
        root = ET.Element(class_info.name)  # Создаю корневой элемент с именем класса

        # Добавляем атрибуты как вложенные элементы
        for attr in class_info.attributes:
            attr_elem = ET.SubElement(root, attr.name)
            attr_elem.text = str(attr.type)

        # Добавляем дочерние классы
        for child in class_info.children:
            child_elem = ConfigXMLGenerator.generate(child)
            root.append(child_elem)

        return root

    @staticmethod
    def save(root, output_path):
        # Форматируем XML
        rough_string = ET.tostring(root, encoding='utf-8')  #
        reparsed = minidom.parseString(rough_string)
        pretty_xml = reparsed.toprettyxml(indent="  ")

        # Удаляем лишнюю строку с декларацией xml
        pretty_xml = '\n'.join(line for line in pretty_xml.splitlines() if not line.startswith('<?xml'))

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(pretty_xml)


class MetaJSONGenerator:
    """Генератор meta.json."""
    @staticmethod
    def generate(classes):
        meta = []
        for cls in classes.values():
            entry = {
                "class": cls.name,
                "documentation": cls.documentation,
                "isRoot": cls.is_root,
                "max": cls.max,
                "min": cls.min,
                "parameters": []
            }

            for attr in cls.attributes:  # Прохожу по атрибутам
                entry["parameters"].append({"name": attr.name, "type": attr.type})
            # Добавляем дочерние классы
            for child in cls.children:
                entry["parameters"].append({"name": child.name, "type": "class"})
            meta.append(entry)
        return meta

    @staticmethod
    def save(meta, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=4)


class DeltaJSONGenerator:
    """Генератор delta.json."""
    @staticmethod
    def generate(config, patched_config):
        delta = {"additions": [], "deletions": [], "updates": []}
        config_keys = set(config.keys())
        patched_keys = set(patched_config.keys())

        # Additions
        for key in patched_keys - config_keys:  # Ищу новые ключи
            delta["additions"].append({"key": key, "value": patched_config[key]})

        # Deletions
        for key in config_keys - patched_keys:
            delta["deletions"].append(key)

        # Updates
        for key in config_keys & patched_keys:
            if config[key] != patched_config[key]:
                delta["updates"].append({
                    "key": key,
                    "from": config[key],
                    "to": patched_config[key]
                })
        return delta

    @staticmethod
    def save(delta, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(delta, f, indent=4)


class ResPatchedConfigGenerator:
    """Генератор res_patched_config.json."""
    @staticmethod
    def generate(config, delta):
        result = config.copy()
        # Применяем deletions
        for key in delta["deletions"]:
            result.pop(key, None)
        # Применяем updates
        for update in delta["updates"]:
            result[update["key"]] = update["to"]
        # Применяем additions
        for addition in delta["additions"]:
            result[addition["key"]] = addition["value"]
        return result

    @staticmethod
    def save(result, output_path):
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)


def main():
    """Основная функция программы."""
    try:
        required_files = [
            os.path.join(INPUT_DIR, "impulse_test_input.xml"),
            os.path.join(INPUT_DIR, "config.json"),
            os.path.join(INPUT_DIR, "patched_config.json"),
        ]
        for file in required_files:
            if not os.path.exists(file):
                raise FileNotFoundError(f"Входной файл {file} не найден")

        # Парсинг XML
        parser = ModelParser(os.path.join(INPUT_DIR, "impulse_test_input.xml"))

        # Генерация config.xml
        root_class = parser.get_root_class()  # Беру корневой класс
        config_root = ConfigXMLGenerator.generate(root_class)  # Генерирую XML-структуру
        ConfigXMLGenerator.save(
            config_root,
            os.path.join(OUTPUT_DIR, "config.xml")
        )

        # Генерация meta.json
        meta = MetaJSONGenerator.generate(parser.classes)  # Генерирую мета-информацию
        MetaJSONGenerator.save(
            meta,
            os.path.join(OUTPUT_DIR, "meta.json")
        )

        # Чтение config.json и patched_config.json
        with open(os.path.join(INPUT_DIR, "config.json"), "r", encoding="utf-8") as f:
            config = json.load(f)  # Читаю config
        with open(os.path.join(INPUT_DIR, "patched_config.json"), "r", encoding="utf-8") as f:
            patched_config = json.load(f)

        # Генерация delta.json
        delta = DeltaJSONGenerator.generate(config, patched_config)
        DeltaJSONGenerator.save(
            delta,
            os.path.join(OUTPUT_DIR, "delta.json")
        )

        # Генерация res_patched_config.json
        res_patched = ResPatchedConfigGenerator.generate(config, delta)
        ResPatchedConfigGenerator.save(
            res_patched,
            os.path.join(OUTPUT_DIR, "res_patched_config.json")
        )

    except FileNotFoundError as e:
        print(f"Ошибка: {e}")
        exit(1)
    except ET.ParseError as e:
        print(f"Ошибка парсинга XML: {e}")
        exit(1)
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга JSON: {e}")
        exit(1)
    except ValueError as e:
        print(f"Ошибка в данных: {e}")
        exit(1)


if __name__ == "__main__":
    main()