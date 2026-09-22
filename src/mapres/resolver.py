from .tokenizer import Tokenizer
from .parser import Parser
from .evaluator import Evaluator
from .layers import LayerStack
from .cache import LRUCache
from .exceptions import MapResError


class MapResolver:
    '''
    AST-based resolver for mapres.

    Pipeline:
        tokenize → parse → evaluate → return string

    Supports:
        - hierarchical identifiers
        - nested tokens (single argument)
        - multiple map layers
        - ctx fallback
        - caching (optional)
        - per-map missing-key modes via __missing_key__
    '''

    def __init__(self, layers=None, cache: bool = False, cache_size: int = 1024):
        self.layers = layers or LayerStack()
        self.cache_enabled = cache
        self.cache = LRUCache(cache_size) if cache else None

    # public api
    def res(self, text: str, *, extra_maps=None, override_maps=None, **ctx) -> str:
        '''
        Resolve a template string using:
            - tokenizer
            - parser
            - evaluator
            - layerstack
            - ctx

        Missing-key behavior is controlled by:
            - datamap.__missing_key__ on any map in the layerstack
              ('error', 'silent', 'placeholder', 'raw')
        '''

        try:
            # caching
            cache_key = None
            if self.cache_enabled:
                cache_key = (text, tuple(sorted(ctx.items())))
                cached = self.cache.get(cache_key)
                if cached is not None:
                    return cached

            # build working layerstack
            layerstack = self._build_layerstack(extra_maps, override_maps)

            # determine missing-key mode
            missing_mode = self._resolve_missing_key_mode(layerstack)

            # tokenize
            tokens = Tokenizer(text).tokenize()

            # parse
            ast = Parser(tokens).parse()

            # evaluate
            evaluator = Evaluator(layerstack, ctx, missing_key_mode=missing_mode)
            result = evaluator.evaluate(ast)

            # store cache
            if self.cache_enabled and cache_key is not None:
                self.cache.set(cache_key, result)

            return result

        except MapResError as exc:
            # propagate MapResError as-is
            raise

        except Exception as exc:
            # wrap any other exception
            raise MapResError(f'Resolver error: {exc}') from exc

    # layerstack building
    def _build_layerstack(self, extra_maps, override_maps):
        '''
        Build a temporary layerstack for this resolution call.
        Supports:
            - override maps (priority 0)
            - extra maps (priority 999)
            - normal layers (existing priorities)
        '''

        if override_maps is not None:
            temp = LayerStack()
            temp.add_layer(override_maps, priority=0)
            return temp

        if extra_maps is not None:
            temp = self.layers.clone()
            temp.add_layer(extra_maps, priority=999)
            return temp

        return self.layers

    def _resolve_missing_key_mode(self, layerstack: LayerStack) -> str:
        '''
        Determine missing-key mode from maps in the given layerstack.

        First map that defines __missing_key__ wins.
        Defaults to 'error' if none are set.
        '''
        for m in layerstack.all_maps():
            mode = getattr(m, '__missing_key__', None)
            if mode is not None:
                return mode
        return 'error'


# simple global usage
_DEFAULT_RESOLVER = MapResolver()

def setGlobalMaps(*maps, priority=0):
    '''
    Register one or more global maps.
    Supports:
        - classes
        - instances
        - lists/tuples of maps
    '''

    flat = []

    # flatten lists/tuples
    for m in maps:
        if isinstance(m, (list, tuple)):
            flat.extend(m)
        else:
            flat.append(m)

    for m in flat:
        # instantiate classes
        if isinstance(m, type):
            try:
                m = m()
            except TypeError:
                pass

        _DEFAULT_RESOLVER.layers.add_layer(m, priority=priority)


def res(text: str, **ctx) -> str:
    '''Simple global resolution.'''
    return _DEFAULT_RESOLVER.res(text, **ctx)

def rprint(text: str, *args, sep=' ', end='\n', file=None, flush=False, **ctx) -> None:
    '''Simple global resolution and print.'''
    print(res(text, **ctx), *args, sep=sep, end=end, file=file, flush=flush)

res.setGlobalMaps = setGlobalMaps
rprint.setGlobalMaps = setGlobalMaps
