# BSD 3-Clause License
#
# Copyright (c) 2018, Regents of the University of California
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of the copyright holder nor the names of its
#   contributors may be used to endorse or promote products derived from
#   this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# -*- coding: utf-8 -*-
from abc import ABC
from typing import Any, Union, Sequence, Tuple

import pkg_resources
from pathlib import Path

from pybag.enum import DesignOutput

from bag.design.module import Module
from bag.design.database import ModuleDB
from bag.util.immutable import Param

from ..layout.enum import MOSType


class SchTemplate(Module, ABC):
    """An (abstract) extension to Module that adds an 'add_instance' function, which
    enables creation of BAG-generated netlists without OA-created schematic templates.

    In the current implementation of BAG, this is not a good way to do OA symbols, so
    this class should be mainly used for netlists. For fully custom symbols (and schematics),
    we currently recommend still using the standard OA-created schematic flow.
    """

    yaml_file = pkg_resources.resource_filename(__name__,
                                                str(Path('netlist_info',
                                                         'sch_template.yaml')))

    def __init__(self, database: ModuleDB, params: Param, **kwargs: Any) -> None:
        Module.__init__(self, self.yaml_file, database, params, **kwargs)
        self.prev_name = 'XINST'  # name of reference cell
        self.prev_pins = ['IN', 'OUT', 'VSUP']  # names of reference pins

    def get_master_basename(self) -> str:
        """Get the master cell name from the class name.
        By defaults, Module.get_master_basename returns the original cell_name, even 
        when the master is replaced. For this cell, it will always be 'sch_template'.
        If this template gets tested (e.g. a SchTemplate contains a SchTemplate),
        the nested instance would have its self._cell_name set before the above instance
        could call register_master, resulting in a naming overlap conflict.
        This wouldn't normally happen because nested instances don't make sense.
        
        The possible fixes are:
        - Require any inheriter of SchTemplate to define its own get_master_basename
        - Modify the function here to behave more like TemplateBase (this is the correct
            long term fix and should be pulled in.)
        
        The function here borrows from the name convention in ModuleDB
        """
        cls_name = self.__class__.__name__
        base_name = cls_name.split('__')[-1]
        return base_name

    def get_model_path(self, output_type: DesignOutput, view_name: str = '') -> Path:
        """Returns the model file path. 
        The default function Module.get_model_path relies on self._netlist_dir. This will 
        point to the location of the yamls in xbase, i.e. xbase/src/xbase/schematic/netlist_info.
        We would like to reference our current class. We will assume that the location is to be
        "__CLASS__/src/__CLASS__/schematic/models".
        This also changes the basename functionality versus Module.get_model_path so that
        we correctly get the new class.
        """
        basename = self.get_master_basename()

        file_name = f'{basename}.{output_type.extension}'
        work_dir: Path = self._netlist_dir.parent.parent.parent.parent.parent  # BAG work dir
        cls_name = self.__class__.__name__
        lib_name = cls_name.split('__')[0]
        path: Path = work_dir / lib_name / 'src' / lib_name / 'schematic/models' / file_name
        if not path.is_file():
            fallback_type = output_type.fallback_model_type
            if fallback_type is not output_type:
                # if there is a fallback model type defined, try to return that model file
                # instead.
                test_path = path.with_name(f'{basename}.{fallback_type.extension}')
                if test_path.is_file():
                    return test_path

        return path

    def add_instance(self, inst_name: str, lib_name: str = '', cell_name: str = '', 
                     conns: Sequence[Tuple[str, str]] = None, dx: int = 0, dy: int = 0,
                     module_cls: Module = None):
        """Adds instance by arraying instance and replacing master
        2 methods of picking the new master class:
        - Pass lib_name and cell_name, similar to other existing BAG methods
        - Pass in the module class directly (WIP)
        """
        if not conns:
            conns = []
        if not module_cls:
            if (not lib_name) or (not cell_name):
                raise ValueError("If module_cls is not provided, \
                    both lib_name and cell_name must be defined")
        
        prev_name = self.prev_name

        # Trick to move almost 0, 0
        if dx == 0 and dy == 0:
            dx = 1
        
        # array original cell, avoiding name reuse
        self.array_instance(prev_name, ['X_0', inst_name], dx=dx, dy=dy)
        self.rename_instance('X_0', prev_name)

        # replace instance master
        if module_cls:
            """
            inst._ptr.update_master requires a lib and a cell_name, so just getting module_cls
            is not enough
            """
            raise ValueError("Not currently supported")
        else:
            self.replace_instance_master(inst_name, lib_name, cell_name)

        # reconnect instance
        if conns:
            self.reconnect_instance(inst_name, conns)
    
    def add_transistor(self, inst_name: str, mos_type: Union[str, MOSType], stack: bool = False,
                       conns: Sequence[Tuple[str, str]] = None, dx: int = 0, dy: int = 0):
        if not conns:
            conns = []

        """Adds a 4-terminal MOS"""
        if isinstance(mos_type, str):
            mos_type = MOSType[mos_type]
        
        lib_name = 'xbase' if stack else 'BAG_prim'
        if mos_type == MOSType.nch:
            cell_name = 'nmos4_stack' if stack else 'nmos4_standard'
        elif mos_type == MOSType.pch:
            cell_name = 'pmos4_stack' if stack else 'pmos4_standard'
        else:
            raise ValueError("Unsupported mos_type for add_transistor: ", str(mos_type))
        
        self.add_instance(inst_name, lib_name, cell_name, conns, dx, dy)

    def post_design(self, **kwargs: Any) -> None:
        """Hook to remove template pins and instances"""
        self.remove_instance('XINST')

        for pin in self.prev_pins:
            self.remove_pin(pin)
