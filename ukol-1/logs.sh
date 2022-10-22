#!/bin/bash

vagrant docker-logs  | grep -F '[' |sort -k3
