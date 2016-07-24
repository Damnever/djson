# -*- coding: utf-8 -*-

from __future__ import absolute_import

from .reader import TokenReader
from .consts import State, Token
from .excs import JSONDecodeError, _NoMoreDataError


def loads(s):
    reader = TokenReader(s)
    decoder = JSONDecoder(reader)
    try:
        return decoder.parse()
    except _NoMoreDataError:
        decoder._token_illegal()


load = loads


class JSONDecoder(object):

    def __init__(self, reader):
        self._reader = reader
        self._state = State(State.EXPECT_OBJECT_BEGIN)
        self._stack = _Stack()
        self._processers = {
            Token.ILLEGAL: self._token_illegal,
            Token.OBJECT_BEGIN: self._token_object_begin,
            Token.OBJECT_END: self._token_object_end,
            Token.ARRAY_BEGIN: self._token_array_begin,
            Token.ARRAY_END: self._token_array_end,
            Token.STRING: self._token_string,
            Token.SEP_COMMA: self._token_sep_comma,
            Token.SEP_COLON: self._token_sep_colon,
            Token.NUMBER: self._token_number,
            Token.BOOLEAN: self._token_boolean,
            Token.NULL: self._token_null,
            Token.EMPTY: self._token_empty,
        }

    def parse(self):
        while 1:
            token = self._reader.next_token()
            if token == Token.JSON_END:
                break
            self._processers[token]()
        if self._stack.length() != 1:
            self._token_illegal()

        json_obj = self._stack.pop()
        if json_obj.type_ != _StackValue.TYPE_OBJECT:
            self._token_illegal()
        return json_obj.value

    def _token_object_begin(self):
        if self._state.has(State.EXPECT_OBJECT_BEGIN):
            self._stack.push(_StackValue.new_object())
        else:
            raise JSONDecodeError("Unexpected character: '{'")

    def _token_object_end(self):
        # may be a value for k/v pair, or array item
        stack = self._stack
        state = self._state
        err = JSONDecodeError("Unexpected character: '}'")
        if not state.has(State.EXPECT_OBJECT_END) or stack.is_empty():
            raise err

        v_obj = stack.pop()
        if stack.is_empty() and v_obj.type_ == _StackValue.TYPE_OBJECT:
            stack.push(v_obj)
            state.reset(State.EXPECT_JSON_END)
            return

        type_ = stack.top_type()
        if type_ == _StackValue.TYPE_ARRAY:
            self._val_as_array_item(v_obj.value)
        elif type_ == _StackValue.TYPE_OBJ_KEY:
            self._val_as_object_value(v_obj.value, err)
        else:
            raise err


    def _token_array_begin(self):
        if self._state.has(State.EXPECT_ARRAY_BEGIN):
            self._stack.push(_StackValue.new_array())
        else:
            raise JSONDecodeError("Unexpected character: '['")

    def _token_array_end(self):
        # may be a value for k/v pair, or array item
        stack = self._stack
        state = self._state
        err = JSONDecodeError("Unexpected character: ']'")
        if stack.is_empty() or not state.has(State.EXPECT_ARRAY_END):
            raise err

        v_arr = stack.pop()
        if stack.is_empty():
            raise err
        type_ = stack.top_type()
        if type_ == _StackValue.TYPE_ARRAY:
            self._val_as_array_item(v_arr.value)
        elif type_ == _StackValue.TYPE_OBJ_KEY:
            self._val_as_object_value(v_arr.value, err)
        else:
            raise err

    def _token_string(self):
        # as a key, or value, or array item
        val_s = self._reader.token_as_value()
        err = JSONDecodeError("Unexpected string value: '{0}'".format(val_s))
        self._single_value_token(val_s, err)

    def _token_number(self):
        val_n = self._reader.token_as_value()
        err = JSONDecodeError("Unexpected number value: '{0}'".format(val_n))
        self._single_value_token(val_n, err)

    def _token_boolean(self):
        val_b = self._reader.token_as_value()
        err = JSONDecodeError("Unexpected boolean value: '{0}'".format(val_b))
        self._single_value_token(val_b, err)

    def _token_null(self):
        val_null = self._reader.token_as_value()
        err = JSONDecodeError("Unexpected null value: '{0}'".format(val_null))
        self._single_value_token(val_null, err)

    def _token_sep_comma(self):
        stack = self._stack
        state = self._state
        err = JSONDecodeError("Unexpected comma: ','")
        if stack.is_empty() or not state.has(State.EXPECT_COMMA):
            raise err
        type_ = stack.top_type()
        if type_ == _StackValue.TYPE_ARRAY:
            state.reset(State.EXPECT_VALUE | State.EXPECT_ARRAY_END)
        elif type_ == _StackValue.TYPE_OBJECT:
            state.reset(State.EXPECT_VALUE | State.EXPECT_OBJECT_END)
        else:
            raise err

    def _token_sep_colon(self):
        stack = self._stack
        state = self._state
        err = JSONDecodeError("Unexpected colon: ':'")
        if stack.is_empty() or not state.has(State.EXPECT_COLON):
            raise err
        type_ = stack.top_type()
        if type_ == _StackValue.TYPE_OBJ_KEY:
            state.reset(State.EXPECT_VALUE)
        else:
            raise err

    def _token_illegal(self):
        raise JSONDecodeError("Illegal JSON form.")

    def _token_empty(self):
        pass

    def _single_value_token(self, val, err):
        stack = self._stack
        state = self._state
        if stack.is_empty() or not state.has(State.EXPECT_VALUE):
            raise err

        type_ = stack.top_type()
        if type_ == _StackValue.TYPE_ARRAY:
            self._val_as_array_item(val)
        elif type_ == _StackValue.TYPE_OBJECT:
            self._val_as_object_key(val)
        elif type_ == _StackValue.TYPE_OBJ_KEY:
            self._val_as_object_value(val, err)
        else:
            raise err

    def _val_as_object_key(self, val):
        self._stack.push(_StackValue.new_obj_key(val))
        self._state.reset(State.EXPECT_COLON)

    def _val_as_object_value(self, val, err):
        stack = self._stack
        state = self._state
        if stack.length() < 2:
            raise err

        key = stack.pop()
        obj = stack.peek()
        if obj.type_ != _StackValue.TYPE_OBJECT:
            raise err
        obj.value[key.value] = val
        state.reset(State.EXPECT_COMMA | State.EXPECT_OBJECT_END)

    def _val_as_array_item(self, val):
        self._stack.peek().value.append(val)
        self._state.reset(State.EXPECT_COMMA | State.EXPECT_ARRAY_END)


class _StackValue(object):
    TYPE_OBJECT = 0
    TYPE_ARRAY = 1
    TYPE_OBJ_KEY = 2
    TYPE_VALUE = 3

    def __init__(self, type_, value):
        self._type = type_
        self._value = value

    @property
    def type_(self):
        return self._type

    @property
    def value(self):
        return self._value

    @classmethod
    def new_object(cls):
        return cls(cls.TYPE_OBJECT, dict())

    @classmethod
    def new_array(cls):
        return cls(cls.TYPE_ARRAY, list())

    @classmethod
    def new_obj_key(cls, val):
        return cls(cls.TYPE_OBJ_KEY, val)

    @classmethod
    def new_value(cls, val):
        return cls(cls.TYPE_VALUE, val)

    def __str__(self):
        return "_StackValue<{0}, {1}>".format(self._type, self._value)

    __repr__ = __str__


class _Stack(object):

    def __init__(self):
        self._data = list()
        self._count = 0

    def push(self, val):
        self._data.append(val)
        self._count += 1

    def pop(self):
        self._count -= 1
        return self._data.pop()

    def peek(self):
        return self._data[-1]

    def is_empty(self):
        return self._count == 0

    def length(self):
        return self._count

    def top_type(self):
        return self._data[-1].type_
