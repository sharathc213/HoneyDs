#!/usr/bin/env python

 

class AttribDict(dict):
    def __getattr__(self, name):
        return self.get(name)

    def __setattr__(self, name, value):
        self[name] = value