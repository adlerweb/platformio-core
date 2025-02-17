# Copyright (c) 2019-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import click

from platformio import fs, proc
from platformio.commands.check.defect import DefectItem
from platformio.project.helpers import (get_project_dir, load_project_ide_data)


class CheckToolBase(object):  # pylint: disable=too-many-instance-attributes

    def __init__(self, project_dir, config, envname, options):
        self.config = config
        self.envname = envname
        self.options = options
        self.cpp_defines = []
        self.cpp_includes = []

        self._defects = []
        self._on_defect_callback = None
        self._bad_input = False
        self._load_cpp_data(project_dir, envname)

        # detect all defects by default
        if not self.options.get("severity"):
            self.options['severity'] = [
                DefectItem.SEVERITY_LOW, DefectItem.SEVERITY_MEDIUM,
                DefectItem.SEVERITY_HIGH
            ]
        # cast to severity by ids
        self.options['severity'] = [
            s if isinstance(s, int) else DefectItem.severity_to_int(s)
            for s in self.options['severity']
        ]

    def _load_cpp_data(self, project_dir, envname):
        data = load_project_ide_data(project_dir, envname)
        if not data:
            return
        self.cpp_includes = data.get("includes", [])
        self.cpp_defines = data.get("defines", [])
        self.cpp_defines.extend(
            self._get_toolchain_defines(data.get("cc_path")))

    def get_flags(self, tool):
        result = []
        flags = self.options.get("flags") or []
        for flag in flags:
            if ":" not in flag:
                result.extend([f for f in flag.split(" ") if f])
            elif flag.startswith("%s:" % tool):
                result.extend(
                    [f for f in flag.split(":", 1)[1].split(" ") if f])

        return result

    @staticmethod
    def _get_toolchain_defines(cc_path):
        defines = []
        result = proc.exec_command("echo | %s -dM -E -x c++ -" % cc_path,
                                   shell=True)

        for line in result['out'].split("\n"):
            tokens = line.strip().split(" ", 2)
            if not tokens or tokens[0] != "#define":
                continue
            if len(tokens) > 2:
                defines.append("%s=%s" % (tokens[1], tokens[2]))
            else:
                defines.append(tokens[1])

        return defines

    @staticmethod
    def is_flag_set(flag, flags):
        return any(flag in f for f in flags)

    def get_defects(self):
        return self._defects

    def configure_command(self):
        raise NotImplementedError

    def on_tool_output(self, line):
        line = self.tool_output_filter(line)
        if not line:
            return

        defect = self.parse_defect(line)

        if not isinstance(defect, DefectItem):
            if self.options.get("verbose"):
                click.echo(line)
            return

        if defect.severity not in self.options['severity']:
            return

        self._defects.append(defect)
        if self._on_defect_callback:
            self._on_defect_callback(defect)

    @staticmethod
    def tool_output_filter(line):
        return line

    @staticmethod
    def parse_defect(raw_line):
        return raw_line

    def clean_up(self):
        pass

    def get_project_src_files(self):
        file_extensions = ["h", "hpp", "c", "cc", "cpp", "ino"]
        return fs.match_src_files(get_project_dir(),
                                  self.options.get("filter"), file_extensions)

    def check(self, on_defect_callback=None):
        self._on_defect_callback = on_defect_callback
        cmd = self.configure_command()
        if self.options.get("verbose"):
            click.echo(" ".join(cmd))

        proc.exec_command(
            cmd,
            stdout=proc.LineBufferedAsyncPipe(self.on_tool_output),
            stderr=proc.LineBufferedAsyncPipe(self.on_tool_output))

        self.clean_up()

        return self._bad_input
