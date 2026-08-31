from .ast import TemplateNode, TextNode, IdentNode, CallNode
from .tokenizer import Tokenizer
from .parser import Parser
from .exceptions import MapResError, MissingKeyError


class EvaluationError(MapResError):
    pass


class Evaluator:
    def __init__(self, layerstack, ctx=None, missing_key_mode: str = 'error'):
        '''
        layerstack: LayerStack instance
        ctx:        dict used as highest-priority map
        missing_key_mode:
            - 'error'       → raise MissingKeyError
            - 'silent'      → return raw token unchanged
            - 'placeholder' → return <missing:key>
            - 'raw'         → return raw token unchanged (alias of 'silent' at token level)
        '''
        self.layerstack = layerstack
        self.ctx = ctx or {}
        self._seen = set()  # cycle detection
        self.missing_key_mode = missing_key_mode

    # public api
    def evaluate(self, node):
        return self._eval(node)

    # internal dispatch
    def _eval(self, node):
        if isinstance(node, TemplateNode):
            return self._eval_template(node)

        if isinstance(node, TextNode):
            return node.text

        if isinstance(node, IdentNode):
            return self._eval_ident(node)

        if isinstance(node, CallNode):
            return self._eval_call(node)

        raise EvaluationError(f'Unknown AST node: {node}')

    # re-resolve
    def _re_resolve(self, text: str) -> str:
        tokens = Tokenizer(text).tokenize()
        ast = Parser(tokens).parse()
        return self.evaluate(ast)

    # template
    def _eval_template(self, node: TemplateNode):
        parts = []
        for child in node.children:
            parts.append(self._eval(child))
        out = ''.join(parts)

        # per-map recursion (syntax-scoped)
        recursive_maps = [
            m for m in self.layerstack.all_maps()
            if getattr(m, '__recursive__', False) is True
        ]

        if not recursive_maps:
            return out

        max_depth = max(getattr(m, '__max_depth__', 10) for m in recursive_maps)

        seen = set()
        depth = 0

        while depth < max_depth:
            new_out = self._re_resolve(out)

            if new_out == out:
                break

            if new_out in seen:
                raise EvaluationError('Cycle detected in recursive map resolution')

            seen.add(new_out)
            out = new_out
            depth += 1

        return out

    # identifier
    def _eval_ident(self, node: IdentNode):
        name = node.name

        # cycle detection
        if name in self._seen:
            raise EvaluationError(f'Cycle detected in identifier \'{name}\'')
        self._seen.add(name)

        parts = name.split('.')

        # 1. ctx first
        val = self._lookup_hierarchical(self.ctx, parts)
        if val is not None:
            self._seen.remove(name)
            return str(val)

        # 2. syntax-bound maps
        for m in self.layerstack.all_maps():
            if getattr(m, '__syntax__', None) not in (None, node.syntax):
                continue

            d = self._map_to_dict(m)
            val = self._lookup_hierarchical(d, parts)
            if val is not None:
                self._seen.remove(name)
                return str(val)

        self._seen.remove(name)
        return self._handle_missing_ident(node)

    # call (nested token)
    def _eval_call(self, node: CallNode):
        outer = node.name

        if outer in self._seen:
            raise EvaluationError(f'Cycle detected in call \'{outer}\'')
        self._seen.add(outer)

        arg_value = self._eval(node.arg)
        parts = [outer, arg_value]

        # ctx first
        val = self._lookup_hierarchical(self.ctx, parts)
        if val is not None:
            self._seen.remove(outer)
            return str(val)

        # syntax-bound maps
        for m in self.layerstack.all_maps():
            if getattr(m, '__syntax__', None) not in (None, node.syntax):
                continue

            d = self._map_to_dict(m)
            val = self._lookup_hierarchical(d, parts)
            if val is not None:
                self._seen.remove(outer)
                return str(val)

        self._seen.remove(outer)
        return self._handle_missing_call(node, arg_value)

    # helpers
    def _map_to_dict(self, m):
        if hasattr(m, 'as_map'):
            return m.as_map()
        if isinstance(m, dict):
            return m
        raise EvaluationError(f'Invalid map object: {m}')

    def _lookup_hierarchical(self, root, parts):
        cur = root
        for p in parts:
            if not isinstance(cur, dict):
                return None
            if p not in cur:
                return None
            cur = cur[p]
        return cur

    # missing-key handling (token-level)
    def _delims_for_syntax(self, syntax_name: str):
        table = {
            'angles': ('<', '>'),
            'braces': ('{{', '}}'),
            'dollars': ('${', '}'),
            'percents': ('%', '%'),
            'pipes': ('|', '|'),
            'colons': (':', ':'),
        }
        return table.get(syntax_name, ('<', '>'))

    def _handle_missing_ident(self, node: IdentNode):
        name = node.name
        open_, close_ = self._delims_for_syntax(node.syntax)
        raw_token = f'{open_}{name}{close_}'

        mode = self.missing_key_mode or 'error'

        if mode in ('silent', 'raw'):
            # token-level fallback: leave the unresolved token as-is
            return raw_token

        if mode == 'placeholder':
            return f'<missing:{name}>'

        # default: error
        raise MissingKeyError(name, token=raw_token)

    def _handle_missing_call(self, node: CallNode, arg_value: str):
        outer = node.name
        open_, close_ = self._delims_for_syntax(node.syntax)
        raw_token = f'{open_}{outer}({arg_value}){close_}'
        key_repr = f'{outer}({arg_value})'

        mode = self.missing_key_mode or 'error'

        if mode in ('silent', 'raw'):
            return raw_token

        if mode == 'placeholder':
            return f'<missing:{key_repr}>'

        raise MissingKeyError(key_repr, token=raw_token)
