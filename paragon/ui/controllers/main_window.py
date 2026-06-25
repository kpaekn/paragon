import logging
import traceback

from PySide6 import QtCore
from PySide6.QtCore import QSortFilterProxyModel
from PySide6.QtGui import QIcon, QActionGroup, QAction
from PySide6.QtWidgets import QInputDialog, QFontDialog, QMessageBox, QFileDialog
from paragon.ui import utils

from paragon.core import backup
from paragon.core import change_packages
from paragon.core import fe14_icon_json
from paragon.model.game import Game
from paragon.model.multi_model import MultiModel
from paragon.model.node_model import NodeModel
from paragon.ui.auto_widget_generator import AutoWidgetGenerator
from paragon.ui.controllers.about import About
from paragon.ui.controllers.error_dialog import ErrorDialog
from paragon.ui.controllers.fe10_main_widget import FE10MainWidget
from paragon.ui.controllers.fe13_main_widget import FE13MainWidget
from paragon.ui.controllers.fe14_main_widget import FE14MainWidget
from paragon.ui.controllers.fe15_main_widget import FE15MainWidget
from paragon.ui.controllers.fe9_main_widget import FE9MainWidget
from paragon.ui.views.ui_main_window import Ui_MainWindow


class MainWindow(Ui_MainWindow):
    def __init__(self, ms, gs):
        super().__init__()
        self.ms = ms
        self.gs = gs
        self.gen = AutoWidgetGenerator(ms, gs)
        self.about_dialog = About()
        self.error_dialog = None
        self.open_uis = {}

        self.node_model = NodeModel(gs.data)
        self.multi_model = MultiModel(gs.data)
        self.node_proxy_model = QSortFilterProxyModel()
        self.node_proxy_model.setSourceModel(self.node_model)
        self.node_proxy_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.multi_proxy_model = QSortFilterProxyModel()
        self.multi_proxy_model.setSourceModel(self.multi_model)
        self.multi_proxy_model.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)
        self.nodes_list.setModel(self.node_proxy_model)
        self.multis_list.setModel(self.multi_proxy_model)

        self.nodes_list.activated.connect(self._on_node_activated)
        self.multis_list.activated.connect(self._on_multi_activated)
        self.save_action.triggered.connect(self._on_save)
        self.save_json_action.triggered.connect(self._on_save_json)
        self.export_action.triggered.connect(self._on_export)
        self.import_action.triggered.connect(self._on_import)
        self.reload_action.triggered.connect(self._on_reload)
        self.close_action.triggered.connect(self._on_close)
        self.quit_action.triggered.connect(self.close)
        self.about_action.triggered.connect(self._on_about)
        self.show_animations_action.triggered.connect(self._on_show_animations)
        self.nodes_search.textChanged.connect(self._on_node_search)
        self.multis_search.textChanged.connect(self._on_multi_search)

        self.debug_log_level_action.triggered.connect(
            lambda: self._on_log_level_changed(logging.DEBUG)
        )
        self.info_log_level_action.triggered.connect(
            lambda: self._on_log_level_changed(logging.INFO)
        )
        self.warning_log_level_action.triggered.connect(
            lambda: self._on_log_level_changed(logging.WARNING)
        )
        self.error_log_level_action.triggered.connect(
            lambda: self._on_log_level_changed(logging.ERROR)
        )
        self.change_font_action.triggered.connect(self._on_change_font)

        self._add_main_widget()
        self.save_json_action.setVisible(self.gs.project.game == Game.FE14)

        self._setup_config()

    def closeEvent(self, event) -> None:
        self.open_uis.clear()
        if hasattr(self, "main_widget"):
            self.main_widget.on_close()
        super().closeEvent(event)

    def _setup_config(self):
        if self.ms.config.show_animations:
            self.show_animations_action.setChecked(self.ms.config.show_animations)
            self._on_show_animations(self.ms.config.show_animations)

        self.theme_action_group = QActionGroup(self)
        for theme in self.ms.config.available_themes():
            action = QAction(theme)
            action.setCheckable(True)
            if theme == self.ms.config.theme:
                action.setChecked(True)
            self.theme_action_group.addAction(action)
            self.theme_menu.addAction(action)
            action.triggered.connect(lambda b=True, t=theme: self._on_theme_changed(t))

        if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
            self.debug_log_level_action.setChecked(True)
        elif logging.getLogger().getEffectiveLevel() == logging.INFO:
            self.info_log_level_action.setChecked(True)
        elif logging.getLogger().getEffectiveLevel() == logging.WARNING:
            self.warning_log_level_action.setChecked(True)
        elif logging.getLogger().getEffectiveLevel() == logging.ERROR:
            self.error_log_level_action.setChecked(True)

    def _on_log_level_changed(self, new_log_level):
        logging.getLogger().setLevel(new_log_level)
        self.ms.config.log_level = new_log_level

    def _on_theme_changed(self, new_theme):
        self.ms.config.theme = new_theme
        utils.info(
            "Theme set. Please restart Paragon to use the new theme.", "Theme Updated"
        )

    def _on_node_search(self):
        self.node_proxy_model.setFilterRegularExpression(self.nodes_search.text())

    def _on_multi_search(self):
        self.multi_proxy_model.setFilterRegularExpression(self.multis_search.text())

    def _add_main_widget(self):
        g = self.gs.project.game
        if g == Game.FE15:
            self.main_widget = FE15MainWidget(self.ms, self.gs, self)
            self.splitter.addWidget(self.main_widget)
            self.splitter.setStretchFactor(1, 1)
        elif g == Game.FE14:
            self.main_widget = FE14MainWidget(self.ms, self.gs, self)
            self.splitter.addWidget(self.main_widget)
            self.splitter.setStretchFactor(1, 1)
            self.resize(950, 600)
        elif g == Game.FE13:
            self.main_widget = FE13MainWidget(self.ms, self.gs, self)
            self.splitter.addWidget(self.main_widget)
            self.splitter.setStretchFactor(1, 1)
        elif g == Game.FE10:
            self.main_widget = FE10MainWidget(self.ms, self.gs, self)
            self.splitter.addWidget(self.main_widget)
            self.splitter.setStretchFactor(1, 1)
        elif g == Game.FE9:
            self.main_widget = FE9MainWidget(self.ms, self.gs, self)
            self.splitter.addWidget(self.main_widget)
            self.splitter.setStretchFactor(1, 1)

    def _on_close(self):
        self.close()
        self.ms.sm.transition("SelectProject", main_state=self.ms)

    def _on_reload(self):
        self.close()
        self.ms.sm.transition("Load", main_state=self.ms, project=self.gs.project)

    def _on_save(self):
        self._save()

    def _on_save_json(self):
        try:
            logging.info("Saving FE14 icon BCH JSON.")
            count = fe14_icon_json.save_icon_bch_json(self.gs.data)
            self.statusBar().showMessage("Save JSON complete.", 5000)
            QMessageBox.information(
                self,
                "Save JSON Complete",
                f"Saved {count} texture sheet{'s' if count != 1 else ''}.",
            )
        except:
            logging.exception("FE14 icon BCH JSON save failed.")
            self.error_dialog = ErrorDialog(traceback.format_exc())
            self.error_dialog.show()

    def _save(self):
        if self.ms.config.backup != "None":
            try:
                backup.backup(
                    self.gs.data,
                    self.gs.project.output_path,
                    self.ms.config.backup == "Smart",
                )
            except:
                logging.exception("Backup failed.")
                self.error_dialog = ErrorDialog(traceback.format_exc())
                self.error_dialog.show()
                return
        try:
            logging.info("Save started.")
            logging.info("Invoking preprocessors before saving.")
            self.gs.write_preprocessors.invoke(self.gs.data)
            logging.info("Preprocessing completed. Saving...")
            result = self.gs.data.write()
            logging.info("Save completed.")
            self.statusBar().showMessage("Save complete.", 5000)

            if self.main_widget.process_compile_result(result.script_compile_result):
                QMessageBox.critical(
                    self,
                    "Script Compiler Error",
                    "Some scripts failed to compile. See the script editor for details.",
                )
        except:
            logging.exception("Save failed.")
            self.error_dialog = ErrorDialog(traceback.format_exc())
            self.error_dialog.show()

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Items", None, "Paragon Item Changes (*.json)"
        )
        if not path:
            return
        try:
            logging.info("Saving before item export.")
            self.gs.write_preprocessors.invoke(self.gs.data)
            result = self.gs.data.write()
            if self.main_widget.process_compile_result(result.script_compile_result):
                QMessageBox.critical(
                    self,
                    "Script Compiler Error",
                    "Some scripts failed to compile. See the script editor for details.",
                )
                return
            count = change_packages.export_items(self.gs.project, path)
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {count} item change{'s' if count != 1 else ''}.",
            )
        except:
            logging.exception("Item export failed.")
            self.error_dialog = ErrorDialog(traceback.format_exc())
            self.error_dialog.show()

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Items", None, "Paragon Item Changes (*.json)"
        )
        if not path:
            return
        try:
            result = change_packages.import_items(self.gs.project, self.gs.data, path)
            details = [
                f"Applied: {result.applied}",
                f"Already applied: {result.already_applied}",
                f"Conflicts: {len(result.conflicts)}",
                f"Errors: {len(result.errors)}",
                "",
                "Imported item changes are now in memory. Use Save to write them.",
            ]
            if result.conflicts:
                details.append("")
                details.append("Conflicts:")
                details.extend(result.conflicts[:20])
                if len(result.conflicts) > 20:
                    details.append(f"... and {len(result.conflicts) - 20} more.")
            if result.errors:
                details.append("")
                details.append("Errors:")
                details.extend(result.errors[:20])
                if len(result.errors) > 20:
                    details.append(f"... and {len(result.errors) - 20} more.")
            QMessageBox.information(self, "Import Complete", "\n".join(details))
        except:
            logging.exception("Item icon import failed.")
            self.error_dialog = ErrorDialog(traceback.format_exc())
            self.error_dialog.show()

    def _on_about(self):
        self.about_dialog.show()

    def _on_show_animations(self, triggered):
        try:
            if triggered:
                self.gs.sprite_animation.start()
            else:
                self.gs.sprite_animation.stop()
        except:
            logging.exception("Failed to start animations.")

    def _on_change_font(self):
        current_font = self.ms.app.font()
        dialog = QFontDialog()
        dialog.setCurrentFont(current_font)
        dialog.exec_()
        self.ms.config.font = dialog.currentFont().toString()
        utils.info(
            "Your changes will be applied after you restart Paragon. "
            "Note that some interfaces may not render as expected with a different font size.",
            "Font Updated",
        )

    def _on_node_activated(self, index):
        node = self.nodes_list.model().data(index, QtCore.Qt.UserRole)
        self.open_node(node)

    def open_node_by_id(self, node_id):
        return self.open_node(self.nodes_list.model().sourceModel().get_by_id(node_id))

    def open_node(self, node):
        try:
            # Check if the UI was generated previously.
            if node in self.open_uis:
                # Use the version we already have.
                self.open_uis[node].show()
                return

            # Not cached. Generate the UI from the typename.
            typename = self.gs.data.type_of(node.rid)
            ui = self.gen.generate_for_type(typename)
            ui.setWindowTitle(f"Paragon - {node.name}")
            ui.setWindowIcon(QIcon("paragon.ico"))
            ui.set_target(node.rid)
            self.open_uis[node] = ui
            ui.show()
        except:
            logging.exception(f"Failed to generate ui for node {node.name}.")
            utils.error(self)

    def _on_multi_activated(self, index):
        # Prompt the user to select a file.
        data = self.gs.data
        multi = self.multis_list.model().data(index, QtCore.Qt.UserRole)
        try:
            keys = data.multi_keys(multi.id)
            choice, ok = QInputDialog.getItem(self, "Select File", "File", keys, -1)
            if not ok:
                return

            # Check if the UI was generated previously.
            key = (multi.id, choice)
            if key in self.open_uis:
                self.open_uis[key].show()
                return

            # Not cached. Open the file and generate a UI.
            rid = data.multi_open(multi.id, choice)
            ui = self.gen.generate_for_type(
                data.type_of(rid), multi_wrap_ids=multi.wrap_ids
            )
            ui.setWindowTitle(f"Paragon - {multi.name}")
            ui.setWindowIcon(QIcon("paragon.ico"))
            if multi.wrap_ids:
                ui.set_target(rid, multi_id=key[0], multi_key=key[1])
            else:
                ui.set_target(rid)
            self.open_uis[key] = ui
            ui.show()
        except:
            logging.exception(f"Failed to open multi {multi.name}.")
            utils.error(self)
