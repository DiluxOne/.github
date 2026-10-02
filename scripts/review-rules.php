<?php
/**
 * The review rules engine: what a kind of project's reviewers send back,
 * declared as data, checked on every pull request.
 *
 * A kind of project (kinds/<kind>/ in this repository) keeps its rules in
 * kinds/<kind>/rules.yml: one entry per thing a review rejected, with an id,
 * a severity, a message, the review it came from and fixtures that prove it.
 * This engine knows the rule *types* and nothing about any kind; a new
 * rejection is a new entry in a rules file, never a new script or workflow.
 * See kinds/README.md.
 *
 *   php review-rules.php --kind <kind> [--repo <dir>] [--tree <dir>] [--format text|github|json] [--only <id,…>]
 *   php review-rules.php --rules <file> …                 (a rules file somewhere else)
 *   php review-rules.php --kind <kind> --suggest-suppressions [--repo <dir>] [--tree <dir>]
 *   php review-rules.php --test
 *
 * --repo is the repository's root (config rules read it, and the
 * suppressions file lives there); --tree is the code that ships (code rules
 * read it; default: the repo). Exit 1 when an error-severity rule fires,
 * 2 on a usage or rules-file error, 0 otherwise. --suggest-suppressions
 * prints the entries the suppressions file is missing, to fill in the
 * reasons. --test runs the engine's own tests and every rule's fixtures in
 * every kinds/<kind>/rules.yml.
 *
 * Rule types (fields in kinds/README.md):
 *   comment               a regular expression over comment tokens
 *   call-arg              an argument of a function call, by position or name
 *   hook-callback         the function a hook is registered with, resolved in
 *                         the tree, and what its body must contain
 *   forbidden-call        a function that must not be called
 *   forbidden-config      a regular expression over configuration files
 *   suppression-allowlist every linter suppression of some checks is listed,
 *                         with a reason, in the repository's suppressions file
 *
 * Rules files are YAML, read by the small parser below (no extension or
 * library is needed on a runner or a contributor's machine). It reads block
 * maps and lists, flow lists of scalars, quoted and plain scalars, literal
 * (|) and folded (>) blocks, and comments; anything else (anchors, tags,
 * flow maps, multiple documents) is refused with its line number, never
 * guessed at.
 *
 * Language adapters read the files (PHP, with PHP's own tokenizer, so a
 * string or a comment is never mistaken for code). A rule names its
 * `language`; the rules file sets the default. Adding a language is a class
 * with the same methods as RR_Php_Adapter, registered in rr_adapter().
 *
 * @package DiluxOne
 */

declare(strict_types=1);

// ---------------------------------------------------------------------------
// YAML subset.
// ---------------------------------------------------------------------------

final class RR_Yaml_Error extends RuntimeException {}

final class RR_Yaml {
	/** @var list<array{indent: int, text: string, no: int}> */
	private array $lines = array();
	private int $pos     = 0;

	/** @return mixed */
	public static function parse( string $source ) {
		$parser = new self();
		$raw    = preg_split( '/\r\n|\n|\r/', $source );

		foreach ( $raw as $i => $line ) {
			$parser->lines[] = array(
				'indent' => strlen( $line ) - strlen( ltrim( $line, ' ' ) ),
				'text'   => $line,
				'no'     => $i + 1,
			);
		}

		$parser->skip_blank();

		if ( $parser->pos < count( $parser->lines ) && '---' === rtrim( $parser->lines[ $parser->pos ]['text'] ) ) {
			++$parser->pos;
			$parser->skip_blank();
		}

		if ( $parser->pos >= count( $parser->lines ) ) {
			return null;
		}

		$value = $parser->node( $parser->lines[ $parser->pos ]['indent'] );
		$parser->skip_blank();

		if ( $parser->pos < count( $parser->lines ) ) {
			$parser->fail( 'unexpected content (a second document, or bad indentation)' );
		}

		return $value;
	}

	private function fail( string $why ): void {
		$no = $this->lines[ min( $this->pos, count( $this->lines ) - 1 ) ]['no'] ?? 0;
		throw new RR_Yaml_Error( "line $no: $why" );
	}

	private function skip_blank(): void {
		while ( $this->pos < count( $this->lines ) ) {
			$text = $this->lines[ $this->pos ]['text'];

			if ( false !== strpos( substr( $text, 0, $this->lines[ $this->pos ]['indent'] + 1 ), "\t" ) && '' !== trim( $text ) ) {
				$this->fail( 'a tab in the indentation' );
			}

			if ( '' !== trim( $text ) && '#' !== ltrim( $text )[0] ) {
				return;
			}

			++$this->pos;
		}
	}

	/** @return mixed */
	private function node( int $indent ) {
		$this->skip_blank();
		$line = $this->lines[ $this->pos ];

		if ( $line['indent'] !== $indent ) {
			$this->fail( 'bad indentation' );
		}

		$body = substr( $line['text'], $indent );

		return ( '-' === $body || 0 === strncmp( $body, '- ', 2 ) ) ? $this->seq( $indent ) : $this->map( $indent );
	}

	/** @return list<mixed> */
	private function seq( int $indent ): array {
		$out = array();

		while ( true ) {
			$this->skip_blank();

			if ( $this->pos >= count( $this->lines ) || $this->lines[ $this->pos ]['indent'] !== $indent ) {
				break;
			}

			$body = substr( $this->lines[ $this->pos ]['text'], $indent );

			if ( '-' !== $body && 0 !== strncmp( $body, '- ', 2 ) ) {
				break;
			}

			$rest = ltrim( substr( $body, 1 ) );

			if ( '' === $rest || '#' === $rest[0] ) {
				++$this->pos;
				$this->skip_blank();

				if ( $this->pos >= count( $this->lines ) || $this->lines[ $this->pos ]['indent'] <= $indent ) {
					$out[] = null;
					continue;
				}

				$out[] = $this->node( $this->lines[ $this->pos ]['indent'] );
				continue;
			}

			if ( $this->is_pair( $rest ) ) {
				// "- key: value": a map whose first key starts where the
				// dash's content does; the following keys line up with it.
				$column                                = $indent + ( strlen( $body ) - strlen( $rest ) );
				$this->lines[ $this->pos ]['text']     = str_repeat( ' ', $column ) . $rest;
				$this->lines[ $this->pos ]['indent']   = $column;
				$out[]                                 = $this->map( $column );
				continue;
			}

			$out[] = $this->scalar_or_block( $rest, $indent );
		}

		return $out;
	}

	/** @return array<string, mixed> */
	private function map( int $indent ): array {
		$out = array();

		while ( true ) {
			$this->skip_blank();

			if ( $this->pos >= count( $this->lines ) || $this->lines[ $this->pos ]['indent'] !== $indent ) {
				break;
			}

			$body = substr( $this->lines[ $this->pos ]['text'], $indent );

			if ( 0 === strncmp( $body, '- ', 2 ) || '-' === $body ) {
				break;
			}

			if ( ! $this->is_pair( $body ) ) {
				$this->fail( 'expected "key: value"' );
			}

			list( $key, $rest ) = $this->split_pair( $body );

			if ( array_key_exists( $key, $out ) ) {
				$this->fail( "duplicate key \"$key\"" );
			}

			if ( '' === $rest || '#' === $rest[0] ) {
				++$this->pos;
				$this->skip_blank();

				if ( $this->pos < count( $this->lines ) ) {
					$next = $this->lines[ $this->pos ];
					$nb   = substr( $next['text'], $next['indent'] );

					if ( $next['indent'] > $indent || ( $next['indent'] === $indent && ( 0 === strncmp( $nb, '- ', 2 ) || '-' === $nb ) ) ) {
						$out[ $key ] = $this->node( $next['indent'] );
						continue;
					}
				}

				$out[ $key ] = null;
				continue;
			}

			$out[ $key ] = $this->scalar_or_block( $rest, $indent );
		}

		return $out;
	}

	private function is_pair( string $text ): bool {
		if ( '"' === $text[0] || "'" === $text[0] ) {
			$end = $this->quoted_end( $text );

			return null !== $end && preg_match( '/^\s*:(\s|$)/', substr( $text, $end + 1 ) ) === 1;
		}

		return preg_match( '/^[^\s#\[\]{},:][^:#]*?:(\s|$)/', $text ) === 1;
	}

	/** @return array{0: string, 1: string} */
	private function split_pair( string $text ): array {
		if ( '"' === $text[0] || "'" === $text[0] ) {
			$end = (int) $this->quoted_end( $text );
			$key = (string) $this->quoted( substr( $text, 0, $end + 1 ) );
			$at  = strpos( $text, ':', $end + 1 );

			return array( $key, trim( substr( $text, (int) $at + 1 ) ) );
		}

		$at = (int) strpos( $text, ':' );

		return array( rtrim( substr( $text, 0, $at ) ), trim( substr( $text, $at + 1 ) ) );
	}

	private function quoted_end( string $text ): ?int {
		$q   = $text[0];
		$len = strlen( $text );

		for ( $i = 1; $i < $len; $i++ ) {
			if ( '"' === $q && '\\' === $text[ $i ] ) {
				++$i;
				continue;
			}

			if ( $text[ $i ] === $q ) {
				if ( "'" === $q && $i + 1 < $len && "'" === $text[ $i + 1 ] ) {
					++$i;
					continue;
				}

				return $i;
			}
		}

		return null;
	}

	/** @return mixed */
	private function scalar_or_block( string $rest, int $indent ) {
		if ( preg_match( '/^([|>])([+-]?)\s*(#.*)?$/', $rest, $m ) ) {
			++$this->pos;

			return $this->block( $indent, '|' === $m[1], $m[2] );
		}

		++$this->pos;

		return $this->scalar( $rest );
	}

	private function block( int $parent, bool $literal, string $chomp ): string {
		$lines  = array();
		$indent = null;

		while ( $this->pos < count( $this->lines ) ) {
			$line = $this->lines[ $this->pos ];

			if ( '' === trim( $line['text'] ) ) {
				$lines[] = '';
				++$this->pos;
				continue;
			}

			if ( null === $indent ) {
				$indent = $line['indent'];
			}

			if ( $line['indent'] < $indent || $line['indent'] <= $parent ) {
				break;
			}

			$lines[] = substr( $line['text'], $indent );
			++$this->pos;
		}

		// Trailing blank lines belong to the chomping, not the text.
		$trailing = 0;

		while ( array() !== $lines && '' === end( $lines ) ) {
			array_pop( $lines );
			++$trailing;
		}

		if ( $literal ) {
			$text = implode( "\n", $lines );
		} else {
			$text = '';

			foreach ( $lines as $i => $l ) {
				if ( 0 === $i ) {
					$text = $l;
				} elseif ( '' === $l ) {
					$text .= "\n";
				} elseif ( '' === $lines[ $i - 1 ] || ' ' === $l[0] ) {
					$text .= ( '' === $lines[ $i - 1 ] ? '' : "\n" ) . $l;
				} else {
					$text .= ' ' . $l;
				}
			}
		}

		if ( '' === $text ) {
			return '';
		}

		if ( '-' === $chomp ) {
			return $text;
		}

		return $text . ( '+' === $chomp ? str_repeat( "\n", $trailing + 1 ) : "\n" );
	}

	/** @return mixed */
	private function scalar( string $text ) {
		$text = trim( $text );

		if ( '' === $text ) {
			return null;
		}

		if ( '"' === $text[0] || "'" === $text[0] ) {
			$end = $this->quoted_end( $text );

			if ( null === $end ) {
				--$this->pos;
				$this->fail( 'an unterminated quoted string (quoted strings are one line here; use | or > for longer text)' );
			}

			$after = trim( substr( $text, (int) $end + 1 ) );

			if ( '' !== $after && '#' !== $after[0] ) {
				--$this->pos;
				$this->fail( 'text after a quoted string' );
			}

			return $this->quoted( substr( $text, 0, (int) $end + 1 ) );
		}

		if ( '[' === $text[0] ) {
			return $this->flow_list( $text );
		}

		if ( '{' === $text[0] ) {
			if ( preg_match( '/^\{\s*\}\s*(#.*)?$/', $text ) ) {
				return array();
			}

			--$this->pos;
			$this->fail( 'flow maps ({ a: b }) are not read here; write the map as a block' );
		}

		if ( in_array( $text[0], array( '&', '*', '!', '%', '@', '`', '?' ), true ) ) {
			--$this->pos;
			$this->fail( 'anchors, aliases, tags and directives are not read here' );
		}

		$text = preg_replace( '/\s+#.*$/', '', $text );

		return self::plain( (string) $text );
	}

	/** @return mixed */
	private static function plain( string $text ) {
		$lower = strtolower( $text );

		if ( '~' === $text || 'null' === $lower ) {
			return null;
		}

		if ( 'true' === $lower ) {
			return true;
		}

		if ( 'false' === $lower ) {
			return false;
		}

		if ( preg_match( '/^-?(0|[1-9][0-9]*)$/', $text ) ) {
			return (int) $text;
		}

		if ( preg_match( '/^-?(0|[1-9][0-9]*)\.[0-9]+$/', $text ) ) {
			return (float) $text;
		}

		return $text;
	}

	private function quoted( string $text ): string {
		$inner = substr( $text, 1, -1 );

		if ( "'" === $text[0] ) {
			return str_replace( "''", "'", $inner );
		}

		return (string) preg_replace_callback(
			'/\\\\(.)/',
			static function ( array $m ): string {
				$map = array(
					'n'  => "\n",
					't'  => "\t",
					'\\' => '\\',
					'"'  => '"',
					'/'  => '/',
					'0'  => "\0",
				);

				return $map[ $m[1] ] ?? '\\' . $m[1];
			},
			$inner
		);
	}

	/** @return list<mixed> */
	private function flow_list( string $text ): array {
		$items = array();
		$now   = '';
		$len   = strlen( $text );
		$i     = 1;

		for ( ; $i < $len; $i++ ) {
			$c = $text[ $i ];

			if ( '"' === $c || "'" === $c ) {
				$end = $this->quoted_end( substr( $text, $i ) );

				if ( null === $end ) {
					--$this->pos;
					$this->fail( 'an unterminated quoted string in a list' );
				}

				$now .= substr( $text, $i, (int) $end + 1 );
				$i   += (int) $end;
				continue;
			}

			if ( '[' === $c || '{' === $c ) {
				--$this->pos;
				$this->fail( 'nested flow collections are not read here' );
			}

			if ( ',' === $c || ']' === $c ) {
				if ( '' !== trim( $now ) ) {
					$items[] = $this->flow_item( trim( $now ) );
				}

				$now = '';

				if ( ']' === $c ) {
					break;
				}

				continue;
			}

			$now .= $c;
		}

		$after = trim( substr( $text, $i + 1 ) );

		if ( $i >= $len || ( '' !== $after && '#' !== $after[0] ) ) {
			--$this->pos;
			$this->fail( 'a flow list must close on its line' );
		}

		return $items;
	}

	/** @return mixed */
	private function flow_item( string $text ) {
		if ( '"' === $text[0] || "'" === $text[0] ) {
			return $this->quoted( $text );
		}

		return self::plain( $text );
	}
}

// ---------------------------------------------------------------------------
// Globs: "**" crosses directories, "*" and "?" do not.
// ---------------------------------------------------------------------------

function rr_glob_regex( string $glob ): string {
	$out = '';
	$len = strlen( $glob );

	for ( $i = 0; $i < $len; $i++ ) {
		if ( '*' === $glob[ $i ] && '*' === ( $glob[ $i + 1 ] ?? '' ) ) {
			if ( '/' === ( $glob[ $i + 2 ] ?? '' ) ) {
				$out .= '(?:.*/)?';
				$i   += 2;
			} else {
				$out .= '.*';
				++$i;
			}
		} elseif ( '*' === $glob[ $i ] ) {
			$out .= '[^/]*';
		} elseif ( '?' === $glob[ $i ] ) {
			$out .= '[^/]';
		} else {
			$out .= preg_quote( $glob[ $i ], '~' );
		}
	}

	return '~^' . $out . '$~';
}

/** @param list<string> $globs */
function rr_glob_any( string $path, array $globs ): bool {
	foreach ( $globs as $glob ) {
		if ( preg_match( rr_glob_regex( $glob ), $path ) ) {
			return true;
		}
	}

	return false;
}

/** A rules file's regular expression, as PCRE: the body as written, `flags` after it. */
function rr_regex( string $body, string $flags = '' ): string {
	return '~' . str_replace( '~', '\\~', $body ) . '~' . $flags;
}

// ---------------------------------------------------------------------------
// The PHP adapter.
// ---------------------------------------------------------------------------

/**
 * One PHP file, tokenized, with what the rule types ask of it: comments,
 * function calls and their arguments, declarations, hook registrations.
 */
final class RR_Php_File {
	public string $path;
	public string $source;
	/** @var list<array{0: int|string, 1: string, 2: int}> every token, a one-character one as [char, char, line] */
	public array $t = array();
	/** @var array<int, int> matching bracket, both ways */
	public array $match = array();
	/** @var list<array{class: string, name: string, open: int, close: int, start: int}> named functions and methods */
	public array $functions = array();
	/** @var list<array{open: int, close: int}> every function body, named or not */
	public array $bodies = array();

	public function __construct( string $path, string $source ) {
		$this->path   = $path;
		$this->source = $source;
		$line         = 1;

		foreach ( token_get_all( $source ) as $token ) {
			if ( is_array( $token ) ) {
				$this->t[] = array( $token[0], $token[1], $token[2] );
				$line      = $token[2] + substr_count( $token[1], "\n" );
			} else {
				$this->t[] = array( $token, $token, $line );
			}
		}

		$this->index();
	}

	private function index(): void {
		$stack   = array();
		$classes = array();
		$count   = count( $this->t );

		for ( $i = 0; $i < $count; $i++ ) {
			$type = $this->t[ $i ][0];

			if ( '{' === $type || T_CURLY_OPEN === $type || T_DOLLAR_OPEN_CURLY_BRACES === $type || '(' === $type || '[' === $type ) {
				$stack[] = $i;
			} elseif ( '}' === $type || ')' === $type || ']' === $type ) {
				$open = array_pop( $stack );

				if ( null !== $open ) {
					$this->match[ $open ] = $i;
					$this->match[ $i ]    = $open;
				}
			}
		}

		for ( $i = 0; $i < $count; $i++ ) {
			$type = $this->t[ $i ][0];

			if ( in_array( $type, array( T_CLASS, T_TRAIT, T_INTERFACE ), true ) || ( defined( 'T_ENUM' ) && T_ENUM === $type ) ) {
				$prev = $this->prev( $i );

				if ( null !== $prev && in_array( $this->t[ $prev ][0], array( T_DOUBLE_COLON, T_NEW ), true ) ) {
					continue;
				}

				$name = $this->next( $i );

				if ( null === $name || T_STRING !== $this->t[ $name ][0] ) {
					continue;
				}

				$open = $name;

				while ( $open < $count && '{' !== $this->t[ $open ][0] ) {
					++$open;
				}

				if ( isset( $this->match[ $open ] ) ) {
					$classes[] = array( strtolower( $this->t[ $name ][1] ), $open, $this->match[ $open ] );
				}

				continue;
			}

			if ( T_FUNCTION !== $type && T_FN !== $type ) {
				continue;
			}

			$j = $this->next( $i );

			if ( null !== $j && '&' === $this->t[ $j ][0] ) {
				$j = $this->next( $j );
			}

			$named = null !== $j && T_FN !== $type && '(' !== $this->t[ $j ][0];
			$paren = $named ? $this->next( (int) $j ) : $j;

			if ( null === $paren || '(' !== $this->t[ $paren ][0] || ! isset( $this->match[ $paren ] ) ) {
				continue;
			}

			$k = $this->match[ $paren ] + 1;

			if ( T_FN === $type ) {
				while ( $k < $count && T_DOUBLE_ARROW !== $this->t[ $k ][0] ) {
					++$k;
				}

				$end = $this->expression_end( $k + 1 );
				$this->bodies[] = array( 'open' => $k, 'close' => $end );
				continue;
			}

			while ( $k < $count && '{' !== $this->t[ $k ][0] && ';' !== $this->t[ $k ][0] ) {
				++$k;
			}

			if ( $k >= $count || ';' === $this->t[ $k ][0] || ! isset( $this->match[ $k ] ) ) {
				continue;
			}

			$this->bodies[] = array( 'open' => $k, 'close' => $this->match[ $k ] );

			if ( $named ) {
				$class = '';

				foreach ( $classes as list( $cname, $copen, $cclose ) ) {
					if ( $i > $copen && $i < $cclose ) {
						$class = $cname;
					}
				}

				$this->functions[] = array(
					'class' => $class,
					'name'  => strtolower( $this->t[ (int) $j ][1] ),
					'open'  => $k,
					'close' => $this->match[ $k ],
					'start' => $i,
				);
			}
		}
	}

	/** Where an arrow function's expression ends: the first , ; ) ] } at its own depth. */
	private function expression_end( int $from ): int {
		$count = count( $this->t );

		for ( $i = $from; $i < $count; $i++ ) {
			$type = $this->t[ $i ][0];

			if ( isset( $this->match[ $i ] ) && $this->match[ $i ] > $i ) {
				$i = $this->match[ $i ];
				continue;
			}

			if ( in_array( $type, array( ',', ';', ')', ']', '}' ), true ) ) {
				return $i - 1;
			}
		}

		return $count - 1;
	}

	public function significant( int $i ): bool {
		return ! in_array( $this->t[ $i ][0], array( T_WHITESPACE, T_COMMENT, T_DOC_COMMENT ), true );
	}

	public function next( int $i ): ?int {
		$count = count( $this->t );

		for ( $j = $i + 1; $j < $count; $j++ ) {
			if ( $this->significant( $j ) ) {
				return $j;
			}
		}

		return null;
	}

	public function prev( int $i ): ?int {
		for ( $j = $i - 1; $j >= 0; $j-- ) {
			if ( $this->significant( $j ) ) {
				return $j;
			}
		}

		return null;
	}

	/** @return list<array{line: int, text: string, index: int}> */
	public function comments(): array {
		$out = array();

		foreach ( $this->t as $i => $token ) {
			if ( T_COMMENT === $token[0] || T_DOC_COMMENT === $token[0] ) {
				$out[] = array(
					'line'  => $token[2],
					'text'  => $token[1],
					'index' => $i,
				);
			}
		}

		return $out;
	}

	/**
	 * Every call of a function (not a method) by name, between two indexes.
	 *
	 * A name is matched as written (T_STRING), fully qualified
	 * (`\add_menu_page`, T_NAME_FULLY_QUALIFIED; or the separator and the
	 * name on PHP 7) or qualified (`Ns\fn`, T_NAME_QUALIFIED). The returned
	 * name is lower case without a leading backslash.
	 *
	 * With $methods, method calls too, named `->name` or `::name`.
	 *
	 * @return list<array{name: string, index: int, line: int, paren: int}>
	 */
	public function calls( int $from = 0, ?int $to = null, bool $methods = false ): array {
		$to   = $to ?? count( $this->t ) - 1;
		$out  = array();
		$fqn  = defined( 'T_NAME_FULLY_QUALIFIED' ) ? T_NAME_FULLY_QUALIFIED : -1;
		$qual = defined( 'T_NAME_QUALIFIED' ) ? T_NAME_QUALIFIED : -1;

		for ( $i = $from; $i <= $to; $i++ ) {
			$type = $this->t[ $i ][0];

			if ( T_STRING !== $type && $fqn !== $type && $qual !== $type ) {
				continue;
			}

			$paren = $this->next( $i );

			if ( null === $paren || '(' !== $this->t[ $paren ][0] ) {
				continue;
			}

			$prev = $this->prev( $i );
			$name = $this->t[ $i ][1];

			if ( null !== $prev && T_NS_SEPARATOR === $this->t[ $prev ][0] ) {
				$before = $this->prev( $prev );

				if ( null !== $before && T_STRING === $this->t[ $before ][0] ) {
					continue; // The tail of a PHP 7 qualified name, read with its head.
				}

				$prev = $before;
			}

			$nullsafe = defined( 'T_NULLSAFE_OBJECT_OPERATOR' ) ? T_NULLSAFE_OBJECT_OPERATOR : -1;

			if ( $methods && null !== $prev && in_array( $this->t[ $prev ][0], array( T_OBJECT_OPERATOR, $nullsafe, T_DOUBLE_COLON ), true ) ) {
				$out[] = array(
					'name'  => ( T_DOUBLE_COLON === $this->t[ $prev ][0] ? '::' : '->' ) . strtolower( $name ),
					'index' => $i,
					'line'  => $this->t[ $i ][2],
					'paren' => $paren,
				);
				continue;
			}

			if ( null !== $prev && in_array( $this->t[ $prev ][0], array( T_FUNCTION, T_OBJECT_OPERATOR, $nullsafe, T_DOUBLE_COLON, T_NEW, T_CONST ), true ) ) {
				continue;
			}

			if ( null !== $prev && '&' === $this->t[ $prev ][0] ) {
				$before = $this->prev( $prev );

				if ( null !== $before && T_FUNCTION === $this->t[ $before ][0] ) {
					continue;
				}
			}

			$out[] = array(
				'name'  => strtolower( ltrim( $name, '\\' ) ),
				'index' => $i,
				'line'  => $this->t[ $i ][2],
				'paren' => $paren,
			);
		}

		return $out;
	}

	/**
	 * The arguments of the call whose `(` is at $paren: each one's token
	 * range, its source without comments, and its name when it is named.
	 *
	 * @return list<array{from: int, to: int, text: string, name: string}>
	 */
	public function args( int $paren ): array {
		$close = $this->match[ $paren ] ?? null;

		if ( null === $close ) {
			return array();
		}

		$args  = array();
		$start = $paren + 1;

		for ( $i = $paren + 1; $i <= $close; $i++ ) {
			if ( $i < $close && isset( $this->match[ $i ] ) && $this->match[ $i ] > $i ) {
				$i = $this->match[ $i ];
				continue;
			}

			if ( $i === $close || ',' === $this->t[ $i ][0] ) {
				$arg = $this->arg( $start, $i - 1 );

				if ( '' !== $arg['text'] || $i !== $close ) {
					$args[] = $arg;
				}

				$start = $i + 1;
			}
		}

		return $args;
	}

	/** @return array{from: int, to: int, text: string, name: string} */
	private function arg( int $from, int $to ): array {
		$name  = '';
		$first = null;

		for ( $i = $from; $i <= $to; $i++ ) {
			if ( $this->significant( $i ) ) {
				$first = $i;
				break;
			}
		}

		if ( null !== $first && T_STRING === $this->t[ $first ][0] ) {
			$colon = $this->next( $first );

			if ( null !== $colon && $colon <= $to && ':' === $this->t[ $colon ][0] ) {
				$name = strtolower( $this->t[ $first ][1] );
				$from = $colon + 1;
			}
		}

		return array(
			'from' => $from,
			'to'   => $to,
			'text' => $this->text( $from, $to ),
			'name' => $name,
		);
	}

	/** Source between two indexes, comments left out, whitespace collapsed. */
	public function text( int $from, int $to ): string {
		$out = '';

		for ( $i = $from; $i <= $to; $i++ ) {
			if ( T_COMMENT === $this->t[ $i ][0] || T_DOC_COMMENT === $this->t[ $i ][0] ) {
				continue;
			}

			$out .= $this->t[ $i ][1];
		}

		return trim( (string) preg_replace( '/\s+/', ' ', $out ) );
	}

	/** @return list<int> the significant token indexes between two indexes */
	public function tokens_in( int $from, int $to ): array {
		$out = array();

		for ( $i = $from; $i <= $to; $i++ ) {
			if ( $this->significant( $i ) ) {
				$out[] = $i;
			}
		}

		return $out;
	}

	/** The body (open and close index) of the innermost function around $i, or null at file level. */
	public function enclosing_body( int $i ): ?array {
		$best = null;

		foreach ( $this->bodies as $body ) {
			if ( $i > $body['open'] && $i < $body['close'] && ( null === $best || $body['open'] > $best['open'] ) ) {
				$best = $body;
			}
		}

		return $best;
	}

	/** The class a token sits in, lower case, or ''. */
	public function enclosing_class( int $i ): string {
		foreach ( $this->functions as $fn ) {
			if ( $i > $fn['open'] && $i < $fn['close'] && '' !== $fn['class'] ) {
				return $fn['class'];
			}
		}

		return '';
	}

	/**
	 * The value of a literal string expression: quoted strings, `.` and
	 * interpolation; anything that is not a literal becomes `*`.
	 */
	public function literal( int $from, int $to ): string {
		$out = '';

		foreach ( $this->tokens_in( $from, $to ) as $i ) {
			$type = $this->t[ $i ][0];
			$text = $this->t[ $i ][1];

			if ( T_CONSTANT_ENCAPSED_STRING === $type ) {
				$out .= self::unquote( $text );
			} elseif ( T_ENCAPSED_AND_WHITESPACE === $type ) {
				$out .= $text;
			} elseif ( '.' === $type || '"' === $type || '{' === $type || '}' === $type || T_CURLY_OPEN === $type ) {
				continue;
			} elseif ( '' === $out || '*' !== substr( $out, -1 ) ) {
				$out .= '*';
			}
		}

		return $out;
	}

	public static function unquote( string $text ): string {
		$q     = $text[0] ?? '';
		$inner = substr( $text, 1, -1 );

		if ( "'" === $q ) {
			return str_replace( array( "\\'", '\\\\' ), array( "'", '\\' ), $inner );
		}

		return stripcslashes( $inner );
	}

	/** @var array<int, string>|null line => its code, built once */
	private ?array $code_lines = null;

	/** The source line $line, without its comments and with whitespace collapsed. */
	public function code_on_line( int $line ): string {
		if ( null === $this->code_lines ) {
			$this->code_lines = array();

			foreach ( $this->t as $token ) {
				if ( T_COMMENT !== $token[0] && T_DOC_COMMENT !== $token[0] && T_OPEN_TAG !== $token[0] && T_CLOSE_TAG !== $token[0] ) {
					$this->code_lines[ $token[2] ] = ( $this->code_lines[ $token[2] ] ?? '' ) . $token[1];
				}
			}

			foreach ( $this->code_lines as $n => $code ) {
				$this->code_lines[ $n ] = trim( (string) preg_replace( '/\s+/', ' ', $code ) );
			}
		}

		return $this->code_lines[ $line ] ?? '';
	}
}

final class RR_Php_Adapter {
	/** @var array<string, RR_Php_File> */
	public array $files = array();
	/** @var array<string, list<array{file: string, open: int, close: int}>> function name => bodies */
	private array $functions = array();
	/** @var array<string, list<array{file: string, open: int, close: int}>> class::method => bodies */
	private array $methods = array();
	/** @var array<string, list<array{file: string, open: int, close: int}>> method => bodies, any class */
	private array $by_method = array();

	/** @param list<string> $extensions */
	public function __construct( array $sources ) {
		foreach ( $sources as $path => $source ) {
			$file                 = new RR_Php_File( $path, $source );
			$this->files[ $path ] = $file;

			foreach ( $file->functions as $fn ) {
				$body = array(
					'file'  => $path,
					'open'  => $fn['open'],
					'close' => $fn['close'],
				);

				if ( '' === $fn['class'] ) {
					$this->functions[ $fn['name'] ][] = $body;
				} else {
					$this->methods[ $fn['class'] . '::' . $fn['name'] ][] = $body;
					$this->by_method[ $fn['name'] ][]                     = $body;
				}
			}
		}
	}

	/** @return list<string> */
	public static function extensions(): array {
		return array( 'php' );
	}

	/**
	 * The body a callback names, or null when it is not in the tree (or
	 * names more than one thing).
	 *
	 * @param array{kind: string, name: string, class?: string, file?: string, open?: int, close?: int} $callback
	 * @return array{file: string, open: int, close: int}|null
	 */
	public function resolve( array $callback ): ?array {
		switch ( $callback['kind'] ) {
			case 'closure':
				return array(
					'file'  => (string) $callback['file'],
					'open'  => (int) $callback['open'],
					'close' => (int) $callback['close'],
				);
			case 'function':
				$found = $this->functions[ $callback['name'] ] ?? array();
				break;
			case 'method':
				$found = '' !== ( $callback['class'] ?? '' ) ? ( $this->methods[ $callback['class'] . '::' . $callback['name'] ] ?? array() ) : array();

				if ( array() === $found ) {
					// A parent's method, or an object whose class is not
					// written at the registration: the method's name, when
					// only one class in the tree has it.
					$found = $this->by_method[ $callback['name'] ] ?? array();
				}
				break;
			default:
				$found = array();
		}

		return 1 === count( $found ) ? $found[0] : null;
	}

	/**
	 * The callback an argument names.
	 *
	 * @return array{kind: string, name: string, class?: string, file?: string, open?: int, close?: int}|null
	 */
	public function callback( RR_Php_File $file, array $arg, int $at ): ?array {
		$tokens = $file->tokens_in( $arg['from'], $arg['to'] );

		if ( array() === $tokens ) {
			return null;
		}

		$first = $file->t[ $tokens[0] ];

		// A closure or an arrow function, written in place.
		foreach ( $tokens as $i ) {
			if ( T_FUNCTION === $file->t[ $i ][0] || T_FN === $file->t[ $i ][0] ) {
				foreach ( $file->bodies as $body ) {
					if ( $body['open'] > $i && $body['close'] <= $arg['to'] + 1 ) {
						return array(
							'kind'  => 'closure',
							'name'  => '{closure}',
							'file'  => $file->path,
							'open'  => $body['open'],
							'close' => $body['close'],
						);
					}
				}
			}

			if ( ! in_array( $file->t[ $i ][0], array( T_STATIC, T_FUNCTION, T_FN ), true ) ) {
				break;
			}
		}

		$here = $file->enclosing_class( $at );

		// 'name' or 'Class::name'.
		if ( 1 === count( $tokens ) && T_CONSTANT_ENCAPSED_STRING === $first[0] ) {
			$value = RR_Php_File::unquote( $first[1] );

			if ( preg_match( '/^\\\\?(?:[A-Za-z_][A-Za-z0-9_]*\\\\)*([A-Za-z_][A-Za-z0-9_]*)::([A-Za-z_][A-Za-z0-9_]*)$/', $value, $m ) ) {
				return array(
					'kind'  => 'method',
					'name'  => strtolower( $m[2] ),
					'class' => strtolower( $m[1] ),
				);
			}

			if ( preg_match( '/^\\\\?(?:[A-Za-z_][A-Za-z0-9_]*\\\\)*([A-Za-z_][A-Za-z0-9_]*)$/', $value, $m ) ) {
				return array(
					'kind' => 'function',
					'name' => strtolower( $m[1] ),
				);
			}

			return null;
		}

		// array( X, 'name' ) or [ X, 'name' ].
		$open = $tokens[0];

		if ( T_ARRAY === $first[0] ) {
			$open = $tokens[1] ?? $open;
		}

		if ( '(' === $file->t[ $open ][0] || '[' === $file->t[ $open ][0] ) {
			if ( ( $file->match[ $open ] ?? -1 ) !== end( $tokens ) ) {
				return null;
			}

			$parts = $this->split( $file, $open );

			if ( 2 !== count( $parts ) ) {
				return null;
			}

			$method = $file->tokens_in( $parts[1][0], $parts[1][1] );

			if ( 1 !== count( $method ) || T_CONSTANT_ENCAPSED_STRING !== $file->t[ $method[0] ][0] ) {
				return null;
			}

			$name   = strtolower( RR_Php_File::unquote( $file->t[ $method[0] ][1] ) );
			$target = $file->text( $parts[0][0], $parts[0][1] );
			$class  = '';

			if ( in_array( strtolower( $target ), array( '$this', '__class__', 'self::class', 'static::class', 'get_class( $this )', 'get_class($this)', 'get_called_class()' ), true ) ) {
				$class = $here;
			} elseif ( preg_match( '/^[\'"]\\\\?(?:[A-Za-z_][A-Za-z0-9_]*\\\\)*([A-Za-z_][A-Za-z0-9_]*)[\'"]$/', $target, $m ) || preg_match( '/^\\\\?(?:[A-Za-z_][A-Za-z0-9_]*\\\\)*([A-Za-z_][A-Za-z0-9_]*)::class$/i', $target, $m ) ) {
				$class = strtolower( $m[1] );
			}

			return array(
				'kind'  => 'method',
				'name'  => $name,
				'class' => $class,
			);
		}

		// First-class callables: name(...), $this->name(...), self::name(...).
		$last = count( $tokens ) - 1;

		if ( $last >= 3 && ')' === $file->t[ $tokens[ $last ] ][0] && T_ELLIPSIS === $file->t[ $tokens[ $last - 1 ] ][0] && '(' === $file->t[ $tokens[ $last - 2 ] ][0] ) {
			$name = strtolower( ltrim( $file->t[ $tokens[ $last - 3 ] ][1], '\\' ) );

			if ( $last - 3 === 0 ) {
				return array(
					'kind' => 'function',
					'name' => $name,
				);
			}

			return array(
				'kind'  => 'method',
				'name'  => $name,
				'class' => $here,
			);
		}

		return null;
	}

	/** @return list<array{0: int, 1: int}> the comma-separated parts inside a bracket */
	private function split( RR_Php_File $file, int $open ): array {
		$close = $file->match[ $open ];
		$parts = array();
		$start = $open + 1;

		for ( $i = $open + 1; $i <= $close; $i++ ) {
			if ( $i < $close && isset( $file->match[ $i ] ) && $file->match[ $i ] > $i ) {
				$i = $file->match[ $i ];
				continue;
			}

			if ( $i === $close || ',' === $file->t[ $i ][0] ) {
				if ( '' !== $file->text( $start, $i - 1 ) ) {
					$parts[] = array( $start, $i - 1 );
				}

				$start = $i + 1;
			}
		}

		return $parts;
	}
}

/** The adapter for a language, over a set of files. */
function rr_adapter( string $language, array $sources ): RR_Php_Adapter {
	switch ( $language ) {
		case 'php':
			return new RR_Php_Adapter( $sources );
	}

	throw new InvalidArgumentException( "No adapter for the language \"$language\"." );
}

/** @return list<string> */
function rr_adapter_extensions( string $language ): array {
	switch ( $language ) {
		case 'php':
			return RR_Php_Adapter::extensions();
	}

	throw new InvalidArgumentException( "No adapter for the language \"$language\"." );
}

// ---------------------------------------------------------------------------
// Rules: loading and validation.
// ---------------------------------------------------------------------------

final class RR_Rules_Error extends RuntimeException {}

const RR_TYPES      = array( 'comment', 'call-arg', 'hook-callback', 'forbidden-call', 'forbidden-config', 'suppression-allowlist' );
const RR_SEVERITIES = array( 'error', 'warning', 'notice' );
const RR_FINGERPRINT_LINES    = 3;
const RR_DEFAULT_SUPERGLOBALS = array( '$_GET', '$_POST', '$_REQUEST', '$_COOKIE', '$_FILES', '$_SERVER', '$_ENV' );

/**
 * A rules file, read and checked: every rule has what its type needs, so a
 * typo in a rules file fails the self-test instead of silently passing code.
 *
 * @return array{language: string, exclude: list<string>, exclude-checkout: list<string>, rules: list<array<string, mixed>>}
 */
function rr_load_rules( string $path ): array {
	if ( ! is_file( $path ) ) {
		throw new RR_Rules_Error( "No rules file at $path." );
	}

	try {
		$data = RR_Yaml::parse( (string) file_get_contents( $path ) );
	} catch ( RR_Yaml_Error $e ) {
		throw new RR_Rules_Error( "$path, " . $e->getMessage() );
	}

	if ( ! is_array( $data ) || ! isset( $data['rules'] ) || ! is_array( $data['rules'] ) ) {
		throw new RR_Rules_Error( "$path has no `rules:` list." );
	}

	$language = (string) ( $data['language'] ?? 'php' );
	$exclude  = array_values( array_map( 'strval', (array) ( $data['exclude'] ?? array() ) ) );
	$checkout = array_values( array_map( 'strval', (array) ( $data['exclude-checkout'] ?? array() ) ) );
	$seen     = array();
	$rules    = array();

	foreach ( $data['rules'] as $n => $rule ) {
		$where = "$path, rule " . ( $n + 1 );

		if ( ! is_array( $rule ) ) {
			throw new RR_Rules_Error( "$where is not a map." );
		}

		foreach ( array( 'id', 'type', 'severity', 'message', 'source' ) as $key ) {
			if ( ! isset( $rule[ $key ] ) || '' === trim( (string) $rule[ $key ] ) ) {
				throw new RR_Rules_Error( "$where has no `$key`." );
			}
		}

		$id = (string) $rule['id'];

		if ( ! preg_match( '/^[a-z0-9][a-z0-9-]*$/', $id ) ) {
			throw new RR_Rules_Error( "$where: the id \"$id\" is not kebab-case." );
		}

		if ( isset( $seen[ $id ] ) ) {
			throw new RR_Rules_Error( "$where: the id \"$id\" is used twice." );
		}

		$seen[ $id ] = true;

		if ( ! in_array( $rule['type'], RR_TYPES, true ) ) {
			throw new RR_Rules_Error( "$where ($id): unknown type \"{$rule['type']}\"; one of " . implode( ', ', RR_TYPES ) . '.' );
		}

		if ( ! in_array( $rule['severity'], RR_SEVERITIES, true ) ) {
			throw new RR_Rules_Error( "$where ($id): severity \"{$rule['severity']}\" is not " . implode( ', ', RR_SEVERITIES ) . '.' );
		}

		$fixtures = $rule['fixtures'] ?? null;

		if ( ! is_array( $fixtures ) || array() === (array) ( $fixtures['fail'] ?? array() ) || array() === (array) ( $fixtures['pass'] ?? array() ) ) {
			throw new RR_Rules_Error( "$where ($id): every rule carries fixtures, at least one that must fail and one that must pass." );
		}

		$rule['language'] = (string) ( $rule['language'] ?? $language );
		$rule['scope']    = (string) ( $rule['scope'] ?? ( 'forbidden-config' === $rule['type'] ? 'repo' : 'tree' ) );

		if ( ! in_array( $rule['scope'], array( 'tree', 'repo' ), true ) ) {
			throw new RR_Rules_Error( "$where ($id): scope is tree or repo." );
		}

		$need = array(
			'comment'               => array( 'pattern' ),
			'call-arg'              => array( 'functions', 'when' ),
			'hook-callback'         => array( 'hooks', 'require' ),
			'forbidden-call'        => array( 'functions' ),
			'forbidden-config'      => array( 'files', 'pattern' ),
			'suppression-allowlist' => array( 'sniffs' ),
		);

		foreach ( $need[ $rule['type'] ] as $key ) {
			if ( ! isset( $rule[ $key ] ) ) {
				throw new RR_Rules_Error( "$where ($id): a {$rule['type']} rule needs `$key`." );
			}
		}

		foreach ( array( 'pattern', 'unless', 'ignore-keys' ) as $key ) {
			if ( isset( $rule[ $key ] ) && false === @preg_match( rr_regex( (string) $rule[ $key ], (string) ( $rule['flags'] ?? '' ) ), '' ) ) {
				throw new RR_Rules_Error( "$where ($id): `$key` is not a valid regular expression." );
			}
		}

		// A regex taken from the rules is compiled now, so a typo fails the
		// self-test instead of matching nothing at run time.
		foreach ( (array) ( $rule['require'] ?? array() ) as $need ) {
			foreach ( (array) ( ( (array) $need )['writes'] ?? array() ) as $pattern ) {
				if ( false === @preg_match( '/' . str_replace( '/', '\\/', (string) $pattern ) . '/i', '' ) ) {
					throw new RR_Rules_Error( "$where ($id): `writes` holds \"$pattern\", which is not a valid regular expression." );
				}
			}
		}

		$rules[] = $rule;
	}

	return array(
		'language'         => $language,
		'exclude'          => $exclude,
		'exclude-checkout' => $checkout,
		'rules'            => $rules,
	);
}

// ---------------------------------------------------------------------------
// The run: files, rules, findings.
// ---------------------------------------------------------------------------

/**
 * The files under a directory, relative paths => contents.
 *
 * @param list<string> $exclude globs
 * @param list<string>|null $extensions null for every file
 * @param list<string>|null $include globs a file must match, or null
 * @return array<string, string>
 */
function rr_read_dir( string $dir, array $exclude, ?array $extensions, ?array $include = null ): array {
	$out = array();

	if ( ! is_dir( $dir ) ) {
		return $out;
	}

	$base  = rtrim( $dir, '/' );
	$files = new RecursiveIteratorIterator(
		new RecursiveCallbackFilterIterator(
			new RecursiveDirectoryIterator( $base, FilesystemIterator::SKIP_DOTS ),
			static function ( SplFileInfo $file ) use ( $base ): bool {
				// Never walk into a dependency or a VCS directory: they can be huge.
				return ! ( $file->isDir() && in_array( $file->getFilename(), array( '.git', 'node_modules', 'vendor' ), true ) && dirname( $file->getPathname() ) === $base );
			}
		)
	);

	foreach ( $files as $file ) {
		$path     = (string) $file;
		$relative = ltrim( substr( $path, strlen( $base ) ), '/' );

		if ( ! is_file( $path ) || rr_glob_any( $relative, $exclude ) || ( null !== $include && ! rr_glob_any( $relative, $include ) ) ) {
			continue;
		}

		if ( null !== $extensions && ! in_array( strtolower( pathinfo( $path, PATHINFO_EXTENSION ) ), $extensions, true ) ) {
			continue;
		}

		$out[ $relative ] = (string) file_get_contents( $path );
	}

	ksort( $out );

	return $out;
}

/**
 * Every finding of a set of rules.
 *
 * @param array{language: string, exclude: list<string>, exclude-checkout: list<string>, rules: list<array<string, mixed>>} $set
 * @return list<array{rule: string, severity: string, file: string, line: int, message: string}>
 */
function rr_run( array $set, string $repo, string $tree, ?array $only = null ): array {
	$findings = array();
	$adapters = array();

	foreach ( $set['rules'] as $rule ) {
		if ( null !== $only && ! in_array( $rule['id'], $only, true ) ) {
			continue;
		}

		if ( 'forbidden-config' === $rule['type'] ) {
			// Only the files the rule names: a repository can hold large assets.
			$files = rr_read_dir( $repo, array_merge( array( 'build/**', 'dist/**', '.dx-central/**' ), (array) ( $rule['exclude'] ?? array() ) ), null, array_map( 'strval', (array) $rule['files'] ) );
			$found = rr_forbidden_config( $rule, $files );
		} else {
			$language = $rule['language'];
			$key      = $language . ':' . $rule['scope'];

			if ( ! isset( $adapters[ $key ] ) ) {
				$root             = 'repo' === $rule['scope'] ? $repo : $tree;
				$adapters[ $key ] = rr_adapter( $language, rr_read_dir( $root, rr_excludes( $set, $repo, $root ), rr_adapter_extensions( $language ) ) );
			}

			$adapter = $adapters[ $key ];

			switch ( $rule['type'] ) {
				case 'comment':
					$found = rr_comment( $rule, $adapter );
					break;
				case 'call-arg':
					$found = rr_call_arg( $rule, $adapter );
					break;
				case 'forbidden-call':
					$found = rr_forbidden_call( $rule, $adapter );
					break;
				case 'hook-callback':
					$found = rr_hook_callback( $rule, $adapter );
					break;
				case 'suppression-allowlist':
					$found = rr_suppression_allowlist( $rule, $adapter, $repo );
					break;
				default:
					$found = array();
			}
		}

		foreach ( $found as $f ) {
			$findings[] = array(
				'rule'     => (string) $rule['id'],
				'severity' => (string) ( $f['severity'] ?? $rule['severity'] ),
				'file'     => $f['file'],
				'line'     => $f['line'],
				'message'  => rr_message( (string) ( $f['message'] ?? $rule['message'] ), $f['vars'] ?? array() ),
			);
		}
	}

	usort(
		$findings,
		static fn( array $a, array $b ): int => array( $a['file'], $a['line'], $a['rule'] ) <=> array( $b['file'], $b['line'], $b['rule'] )
	);

	return $findings;
}

/** A message with its {placeholders} filled. */
function rr_message( string $message, array $vars ): string {
	$message = trim( (string) preg_replace( '/\s+/', ' ', $message ) );

	foreach ( $vars as $key => $value ) {
		$message = str_replace( '{' . $key . '}', (string) $value, $message );
	}

	return $message;
}

/** @return list<array{file: string, line: int, vars?: array<string, string>}> */
function rr_comment( array $rule, RR_Php_Adapter $adapter ): array {
	$out     = array();
	$pattern = rr_regex( (string) $rule['pattern'], (string) ( $rule['flags'] ?? '' ) );
	$unless  = isset( $rule['unless'] ) ? rr_regex( (string) $rule['unless'], (string) ( $rule['flags'] ?? '' ) ) : null;

	foreach ( $adapter->files as $path => $file ) {
		foreach ( $file->comments() as $comment ) {
			if ( preg_match( $pattern, $comment['text'], $m ) && ( null === $unless || ! preg_match( $unless, $comment['text'] ) ) ) {
				$out[] = array(
					'file' => $path,
					'line' => $comment['line'],
					'vars' => array( 'match' => trim( $m[0] ) ),
				);
			}
		}
	}

	return $out;
}

/**
 * The functions a call rule names, each with the argument it reads.
 *
 * `functions` is a list (every function, `argument` and `argument-name`
 * from the rule) or a map name => position. `*` is every function.
 *
 * @return array<string, array{position: int|string, name: string}>
 */
function rr_rule_functions( array $rule ): array {
	$out       = array();
	$functions = $rule['functions'];

	if ( is_string( $functions ) ) {
		$functions = array( $functions );
	}

	foreach ( $functions as $key => $value ) {
		if ( is_int( $key ) ) {
			$out[ strtolower( ltrim( (string) $value, '\\' ) ) ] = array(
				'position' => $rule['argument'] ?? 1,
				'name'     => strtolower( (string) ( $rule['argument-name'] ?? '' ) ),
			);
		} else {
			$out[ strtolower( ltrim( (string) $key, '\\' ) ) ] = array(
				'position' => $value,
				'name'     => strtolower( (string) ( $rule['argument-name'] ?? '' ) ),
			);
		}
	}

	return $out;
}

/** @return list<string> the superglobals a rule reads, as variables */
function rr_superglobals( array $rule ): array {
	return array_map(
		static fn( $name ): string => '$' . ltrim( (string) $name, '$' ),
		(array) ( $rule['superglobals'] ?? RR_DEFAULT_SUPERGLOBALS )
	);
}

/** @return list<array{file: string, line: int, vars?: array<string, string>}> */
function rr_call_arg( array $rule, RR_Php_Adapter $adapter ): array {
	$out       = array();
	$functions = rr_rule_functions( $rule );
	$except    = array_map( 'strtolower', (array) ( $rule['except-functions'] ?? array() ) );
	$when      = (array) $rule['when'];
	$globals   = rr_superglobals( $rule );

	foreach ( $adapter->files as $path => $file ) {
		// `*` is every call, methods included: a whole superglobal handed to
		// Foo::from_post() is the same finding as one handed to a function.
		foreach ( $file->calls( 0, null, isset( $functions['*'] ) ) as $call ) {
			$spec = $functions[ $call['name'] ] ?? ( $functions['*'] ?? null );

			if ( null === $spec || in_array( $call['name'], $except, true ) ) {
				continue;
			}

			$args = $file->args( $call['paren'] );

			if ( 'any' === $spec['position'] ) {
				$picked = $args;
			} else {
				$picked = array();

				foreach ( $args as $n => $arg ) {
					if ( ( '' !== $spec['name'] && $arg['name'] === $spec['name'] ) || ( '' === $arg['name'] && $n + 1 === (int) $spec['position'] ) ) {
						$picked[] = $arg;
					}
				}
			}

			foreach ( $picked as $arg ) {
				if ( rr_predicate( $when, $file, $arg, $globals ) ) {
					$out[] = array(
						'file' => $path,
						'line' => $call['line'],
						'vars' => array(
							'function' => $call['name'],
							'value'    => $arg['text'],
						),
					);
					break;
				}
			}
		}
	}

	return $out;
}

/**
 * Whether an argument matches a rule's `when`. Every key given must hold.
 *
 *   present: true             the argument is there and is not null or ''
 *   below: N                  present, and not a number literal of N or more
 *                             (a constant or an expression counts as below:
 *                             it cannot be read here)
 *   contains-superglobal: true  reads a superglobal anywhere inside
 *   is-superglobal: true      is a whole superglobal, nothing else
 *   matches: regex            its source (comments left out) matches
 */
function rr_predicate( array $when, RR_Php_File $file, array $arg, array $globals ): bool {
	$text  = $arg['text'];
	$empty = '' === $text || 'null' === strtolower( $text ) || "''" === $text || '""' === $text;

	foreach ( $when as $key => $value ) {
		switch ( $key ) {
			case 'present':
				if ( (bool) $value === $empty ) {
					return false;
				}
				break;
			case 'below':
				if ( $empty || ( is_numeric( $text ) && (float) $text >= (float) $value ) ) {
					return false;
				}
				break;
			case 'contains-superglobal':
			case 'is-superglobal':
				$tokens = $file->tokens_in( $arg['from'], $arg['to'] );
				$reads  = array_filter( $tokens, static fn( int $i ): bool => T_VARIABLE === $file->t[ $i ][0] && in_array( $file->t[ $i ][1], $globals, true ) );
				$hit    = 'is-superglobal' === $key ? ( 1 === count( $tokens ) && 1 === count( $reads ) ) : array() !== $reads;

				if ( (bool) $value !== $hit ) {
					return false;
				}
				break;
			case 'matches':
				if ( ! preg_match( rr_regex( (string) $value ), $text ) ) {
					return false;
				}
				break;
			default:
				throw new RR_Rules_Error( "Unknown `when` key \"$key\"." );
		}
	}

	return true;
}

/** @return list<array{file: string, line: int, vars?: array<string, string>}> */
function rr_forbidden_call( array $rule, RR_Php_Adapter $adapter ): array {
	$out       = array();
	$functions = array_keys( rr_rule_functions( $rule ) );

	foreach ( $adapter->files as $path => $file ) {
		foreach ( $file->calls() as $call ) {
			if ( in_array( $call['name'], $functions, true ) ) {
				$out[] = array(
					'file' => $path,
					'line' => $call['line'],
					'vars' => array( 'function' => $call['name'] ),
				);
			}
		}
	}

	return $out;
}

/** @return list<array{file: string, line: int, vars?: array<string, string>}> */
function rr_forbidden_config( array $rule, array $files ): array {
	$out     = array();
	$globs   = array_map( 'strval', (array) $rule['files'] );
	$pattern = rr_regex( (string) $rule['pattern'], (string) ( $rule['flags'] ?? '' ) );

	foreach ( $files as $path => $source ) {
		if ( ! rr_glob_any( $path, $globs ) ) {
			continue;
		}

		if ( preg_match_all( $pattern, $source, $matches, PREG_OFFSET_CAPTURE ) ) {
			foreach ( $matches[0] as $match ) {
				$out[] = array(
					'file' => $path,
					'line' => substr_count( substr( $source, 0, $match[1] ), "\n" ) + 1,
					'vars' => array( 'match' => trim( (string) preg_replace( '/\s+/', ' ', $match[0] ) ) ),
				);
			}
		}
	}

	return $out;
}

/**
 * Hook registrations whose callback's body misses what the rule requires.
 *
 *   hooks          globs over the hook's name (a part that is not a literal
 *                  reads as `*`: 'wp_ajax_' . $action is wp_ajax_*)
 *   registrars     the functions that register (default add_action, add_filter)
 *   public-hooks   globs: a callback also registered on one of these is
 *                  skipped (a handler open to visitors needs no capability)
 *   top-level-only true: a registration inside a function body is
 *                  conditional (hooked when that function decides) and skipped
 *   require        a list; each item either
 *                    calls: [fn, …] (+ before-first: superglobal-read, and
 *                    when-no-read: pass to let a body that reads nothing go,
 *                    and writes: [regex, …], the calls that make such a
 *                    body act on the request anyway, so it does not go)
 *                    contains: regex over the body's source (+ label)
 *                  and, on either, unless-calls: [fn, …], a body that
 *                  calls one of these is exempt from that item
 *   superglobals, ignore-keys   what counts as a read: a superglobal whose
 *                  literal key matches ignore-keys is not one (the nonce itself)
 */
function rr_hook_callback( array $rule, RR_Php_Adapter $adapter ): array {
	$out        = array();
	$hooks      = array_map( 'strval', (array) $rule['hooks'] );
	$public     = array_map( 'strval', (array) ( $rule['public-hooks'] ?? array() ) );
	$registrars = array_map( 'strtolower', (array) ( $rule['registrars'] ?? array( 'add_action', 'add_filter' ) ) );
	$top_only   = true === ( $rule['top-level-only'] ?? false );
	$found      = array();
	$open_hooks = array();

	foreach ( $adapter->files as $path => $file ) {
		foreach ( $file->calls() as $call ) {
			if ( ! in_array( $call['name'], $registrars, true ) ) {
				continue;
			}

			$args = $file->args( $call['paren'] );

			if ( count( $args ) < 2 ) {
				continue;
			}

			$hook     = $file->literal( $args[0]['from'], $args[0]['to'] );
			$callback = $adapter->callback( $file, $args[1], $call['index'] );

			if ( null === $callback || '' === $hook ) {
				continue;
			}

			$key = $callback['kind'] . ':' . ( $callback['class'] ?? '' ) . ':' . $callback['name'] . ':' . ( 'closure' === $callback['kind'] ? $path . ':' . $callback['open'] : '' );

			if ( rr_glob_any( $hook, $public ) ) {
				$open_hooks[ $key ] = true;
			}

			if ( ! rr_glob_any( $hook, $hooks ) ) {
				continue;
			}

			if ( $top_only && null !== $file->enclosing_body( $call['index'] ) ) {
				continue;
			}

			$found[] = array( $key, $hook, $callback, $path, $call['line'] );
		}
	}

	$done = array();

	foreach ( $found as list( $key, $hook, $callback, $path, $line ) ) {
		if ( isset( $open_hooks[ $key ] ) || isset( $done[ $key ] ) ) {
			continue;
		}

		$done[ $key ] = true;
		$body         = $adapter->resolve( $callback );

		if ( null === $body ) {
			continue; // Not in the tree: nothing to read.
		}

		$file    = $adapter->files[ $body['file'] ];
		$missing = rr_body_missing( $rule, $file, $body['open'], $body['close'] );

		if ( null !== $missing ) {
			$name  = 'closure' === $callback['kind'] ? 'the closure' : ( '' !== ( $callback['class'] ?? '' ) ? $callback['class'] . '::' . $callback['name'] . '()' : $callback['name'] . '()' );
			$out[] = array(
				'file' => $path,
				'line' => $line,
				'vars' => array(
					'hook'     => $hook,
					'callback' => $name,
					'missing'  => $missing,
				),
			);
		}
	}

	return $out;
}

/** What a body lacks of the rule's `require`, said in a few words, or null. */
function rr_body_missing( array $rule, RR_Php_File $file, int $open, int $close ): ?string {
	$globals = rr_superglobals( $rule + array( 'superglobals' => array( '$_GET', '$_POST', '$_REQUEST', '$_COOKIE', '$_FILES' ) ) );
	$ignore  = isset( $rule['ignore-keys'] ) ? rr_regex( (string) $rule['ignore-keys'] ) : null;
	$read    = null;

	foreach ( $file->tokens_in( $open, $close ) as $i ) {
		if ( T_VARIABLE !== $file->t[ $i ][0] || ! in_array( $file->t[ $i ][1], $globals, true ) ) {
			continue;
		}

		$bracket = $file->next( $i );
		$keytok  = null !== $bracket && '[' === $file->t[ $bracket ][0] ? $file->next( $bracket ) : null;
		$key     = null !== $keytok && T_CONSTANT_ENCAPSED_STRING === $file->t[ $keytok ][0] ? RR_Php_File::unquote( $file->t[ $keytok ][1] ) : null;

		if ( null !== $ignore && null !== $key && preg_match( $ignore, $key ) ) {
			continue;
		}

		$read = $i;
		break;
	}

	$calls = $file->calls( $open, $close );

	foreach ( (array) $rule['require'] as $need ) {
		$need = (array) $need;

		if ( isset( $need['unless-calls'] ) ) {
			$exempt = array_map( static fn( $n ): string => strtolower( ltrim( (string) $n, '\\' ) ), (array) $need['unless-calls'] );

			if ( array() !== array_intersect( $exempt, array_column( $calls, 'name' ) ) ) {
				continue;
			}
		}

		if ( isset( $need['calls'] ) ) {
			$names = array_map( static fn( $n ): string => strtolower( ltrim( (string) $n, '\\' ) ), (array) $need['calls'] );
			$first = null;

			foreach ( $calls as $call ) {
				if ( in_array( $call['name'], $names, true ) ) {
					$first = $call['index'];
					break;
				}
			}

			$label = implode( ' or ', array_map( static fn( string $n ): string => $n . '()', $names ) );

			if ( null === $first ) {
				// A body that never reads the request has nothing unverified
				// to act on, when the rule says so (a router that redirects).
				if ( null === $read && 'superglobal-read' === ( $need['before-first'] ?? '' ) && 'pass' === ( $need['when-no-read'] ?? 'fail' ) ) {
					// … unless it writes: a forged request acts all the same.
					// Method calls count (`$wpdb->query()`, a session
					// manager's `->destroy_all()`), matched without their
					// `->` or `::`.
					$writes = null;

					foreach ( $file->calls( $open, $close, true ) as $call ) {
						$name = ltrim( (string) $call['name'], '->:' );

						foreach ( (array) ( $need['writes'] ?? array() ) as $pattern ) {
							if ( preg_match( '/' . str_replace( '/', '\\/', (string) $pattern ) . '/i', $name ) ) {
								$writes = $call['name'];
								break 2;
							}
						}
					}

					if ( null === $writes ) {
						continue;
					}

					return sprintf( 'it reads nothing of the request but calls %s() with no call to %s', ltrim( $writes, '->:' ), $label );
				}

				return "no call to $label";
			}

			if ( 'superglobal-read' === ( $need['before-first'] ?? '' ) && null !== $read && $read < $first ) {
				return sprintf( '%s reads %s on line %d, before %s', 'it', $file->t[ $read ][1], $file->t[ $read ][2], $label );
			}
		}

		if ( isset( $need['contains'] ) && ! preg_match( rr_regex( (string) $need['contains'], 'i' ), $file->text( $open, $close ) ) ) {
			return (string) ( $need['label'] ?? 'nothing that matches ' . $need['contains'] );
		}
	}

	return null;
}

// ---------------------------------------------------------------------------
// Suppressions.
// ---------------------------------------------------------------------------

/**
 * Every linter suppression in a file: the comment's line, the checks it
 * names ('*' when it names none) and the fingerprint of the code it covers.
 *
 * The fingerprint is the first 12 hex digits of the SHA-1 of the code the
 * suppression covers: the line the comment ends (a trailing
 * `// phpcs:ignore`), or else the next line with code, and the two lines
 * with code after it, comments left out and whitespace collapsed. Moving the
 * block keeps it; changing that code does not. Two suppressions in front of
 * the same code share a fingerprint, and each needs an entry of its own:
 * entries are matched one to one.
 *
 * @return list<array{line: int, sniffs: list<string>, fingerprint: string, covered: string}>
 */
function rr_suppressions( RR_Php_File $file ): array {
	$out   = array();
	$lines = substr_count( $file->source, "\n" ) + 1;

	foreach ( $file->comments() as $comment ) {
		if ( ! preg_match( '/phpcs:(?:ignore|disable)(?![a-z-])([^\n]*)/i', $comment['text'], $m ) ) {
			continue;
		}

		$list   = trim( (string) preg_replace( '/(\s--\s.*|\*\/.*)$/s', '', ' ' . $m[1] ) );
		$sniffs = '' === $list ? array( '*' ) : array_values( array_filter( array_map( 'trim', explode( ',', $list ) ) ) );
		$line   = null;
		$window = array();

		for ( $l = $comment['line']; $l <= $lines && count( $window ) < RR_FINGERPRINT_LINES; $l++ ) {
			$code = $file->code_on_line( $l );

			if ( '' !== $code ) {
				$line     = $line ?? $l;
				$window[] = $code;
			}
		}

		$out[] = array(
			'line'        => $comment['line'],
			'sniffs'      => $sniffs,
			'fingerprint' => rr_fingerprint( $window ),
			'covered'     => $line ?? $comment['line'],
		);
	}

	return $out;
}

/**
 * The fingerprint of the code lines a suppression covers. The checker and
 * --suggest-suppressions both get it from rr_suppressions(), never apart.
 *
 * @param list<string> $lines code, comments left out, whitespace collapsed
 */
function rr_fingerprint( array $lines ): string {
	return substr( sha1( implode( "\n", $lines ) ), 0, 12 );
}

/**
 * The repository's suppressions file: a `suppressions:` list of
 * { file, sniff, fingerprint, reason }.
 *
 * @return list<array{file: string, sniff: string, fingerprint: string, reason: string, line: int}>
 */
function rr_suppression_entries( string $path ): array {
	if ( ! is_file( $path ) ) {
		return array();
	}

	$source = (string) file_get_contents( $path );
	$data   = RR_Yaml::parse( $source );
	$out    = array();

	if ( null === $data ) {
		return $out;
	}

	if ( ! is_array( $data ) || ! is_array( $data['suppressions'] ?? null ) ) {
		throw new RR_Rules_Error( "$path has no `suppressions:` list." );
	}

	// The line of each entry, for the annotation of a stale one.
	preg_match_all( '/^\s*-\s/m', $source, $starts, PREG_OFFSET_CAPTURE );

	foreach ( $data['suppressions'] as $n => $entry ) {
		foreach ( array( 'file', 'sniff', 'fingerprint', 'reason' ) as $key ) {
			if ( ! is_array( $entry ) || '' === trim( (string) ( $entry[ $key ] ?? '' ) ) ) {
				throw new RR_Rules_Error( "$path, entry " . ( $n + 1 ) . ": `$key` is missing or empty." );
			}
		}

		$offset = $starts[0][ $n ][1] ?? 0;
		$out[]  = array(
			'file'        => (string) $entry['file'],
			'sniff'       => (string) $entry['sniff'],
			'fingerprint' => (string) $entry['fingerprint'],
			'reason'      => (string) $entry['reason'],
			'line'        => substr_count( substr( $source, 0, $offset ), "\n" ) + 1,
		);
	}

	return $out;
}

/**
 *   sniffs   regex: the checks whose suppression must be listed
 *   never    regex: checks that can never be listed (an entry for one fails)
 *   file     the suppressions file, from the repository's root
 *            (default .github/review-suppressions.yml)
 */
function rr_suppression_allowlist( array $rule, RR_Php_Adapter $adapter, string $repo ): array {
	$out      = array();
	$sniffs   = rr_regex( (string) $rule['sniffs'] );
	$never    = isset( $rule['never'] ) ? rr_regex( (string) $rule['never'] ) : null;
	$relative = (string) ( $rule['file'] ?? '.github/review-suppressions.yml' );
	$entries  = rr_suppression_entries( rtrim( $repo, '/' ) . '/' . $relative );
	$used     = array();

	foreach ( $adapter->files as $path => $file ) {
		foreach ( rr_suppressions( $file ) as $s ) {
			foreach ( $s['sniffs'] as $sniff ) {
				if ( '*' !== $sniff && ! preg_match( $sniffs, $sniff ) ) {
					continue;
				}

				// One entry per suppression: the first matching entry no other
				// suppression has taken, so identical blocks need one each.
				$listed = null;

				foreach ( $entries as $n => $entry ) {
					if ( ! isset( $used[ $n ] ) && $entry['file'] === $path && $entry['sniff'] === $sniff && $entry['fingerprint'] === $s['fingerprint'] ) {
						$listed = $n;
						break;
					}
				}

				if ( null !== $listed && ( null === $never || ! preg_match( $never, $sniff ) ) && '*' !== $sniff ) {
					$used[ $listed ] = true;
					continue;
				}

				$out[] = array(
					'file' => $path,
					'line' => $s['line'],
					'vars' => array(
						'sniff'       => '*' === $sniff ? 'every check (a bare suppression)' : $sniff,
						'fingerprint' => $s['fingerprint'],
						'entry'       => sprintf( '{ file: %s, sniff: %s, fingerprint: %s, reason: … }', $path, $sniff, $s['fingerprint'] ),
						'list'        => $relative,
					),
				);
			}
		}
	}

	// A reason that points somewhere else is no more a reason in the list
	// than in the comment (`reason-pattern`, with its own message and severity).
	if ( isset( $rule['reason-pattern'] ) ) {
		$pattern = rr_regex( (string) $rule['reason-pattern'], (string) ( $rule['flags'] ?? '' ) );

		foreach ( $entries as $entry ) {
			if ( preg_match( $pattern, $entry['reason'] ) ) {
				$out[] = array(
					'file'     => $relative,
					'line'     => $entry['line'],
					'severity' => (string) ( $rule['reason-severity'] ?? 'warning' ),
					'message'  => (string) ( $rule['reason-message'] ?? 'This reason says the check happens somewhere else.' ),
					'vars'     => array(
						'sniff'       => $entry['sniff'],
						'fingerprint' => $entry['fingerprint'],
						'entry'       => '',
						'list'        => $relative,
					),
				);
			}
		}
	}

	foreach ( $entries as $n => $entry ) {
		if ( isset( $used[ $n ] ) ) {
			continue;
		}

		$cannot = null !== $never && preg_match( $never, $entry['sniff'] );

		if ( ! $cannot && ! preg_match( $sniffs, $entry['sniff'] ) ) {
			continue; // Another allow-list rule's entry.
		}

		$out[] = array(
			'file'    => $relative,
			'line'    => $entry['line'],
			'message' => (string) ( $rule['stale-message'] ?? ( $cannot ? 'This entry lists {sniff}, which can never be allow-listed: remove it and fix the line.' : 'This entry is stale: no suppression of {sniff} in {file} covers code with fingerprint {fingerprint} any more (the code changed or went away). Remove it, or list the suppression as it is now (--suggest-suppressions).' ) ),
			'vars'    => array(
				'file'        => $entry['file'],
				'sniff'       => $entry['sniff'],
				'fingerprint' => $entry['fingerprint'],
				'entry'       => $cannot ? 'this entry: that check can never be allow-listed' : sprintf( 'this entry: no suppression of %s in %s covers code with fingerprint %s any more (the line changed or went away)', $entry['sniff'], $entry['file'], $entry['fingerprint'] ),
				'list'        => $relative,
			),
		);
	}

	return $out;
}

/**
 * What is not read under a root: always `exclude`, and `exclude-checkout`
 * too when the root is the repository's checkout rather than the shipped
 * tree — tests and build output live in a checkout, while a shipped tree
 * holds only what ships, a `build/` of compiled assets included.
 *
 * @param array{exclude: list<string>, exclude-checkout?: list<string>} $set
 * @return list<string>
 */
function rr_excludes( array $set, string $repo, string $root ): array {
	$same = realpath( $repo ) === realpath( $root );

	return array_values( array_merge( $set['exclude'], $same ? (array) ( $set['exclude-checkout'] ?? array() ) : array() ) );
}

/** The entries the suppressions file is missing, as YAML to paste and fill in. */
function rr_suggest_suppressions( array $set, string $repo, string $tree ): string {
	$yaml = '';

	foreach ( $set['rules'] as $rule ) {
		if ( 'suppression-allowlist' !== $rule['type'] ) {
			continue;
		}

		$adapter = rr_adapter( $rule['language'], rr_read_dir( $tree, rr_excludes( $set, $repo, $tree ), rr_adapter_extensions( $rule['language'] ) ) );

		foreach ( rr_suppression_allowlist( $rule, $adapter, $repo ) as $f ) {
			if ( isset( $f['vars']['entry'] ) && 0 === strpos( $f['vars']['entry'], '{' ) ) {
				$file  = $adapter->files[ $f['file'] ] ?? null;
				$code  = null !== $file ? rr_covered_code( $file, $f['line'] ) : '';
				$yaml .= sprintf( "  - file: %s\n    sniff: %s\n    fingerprint: %s\n    reason: \"TODO: why this is safe (%s:%d: %s)\"\n", $f['file'], $f['vars']['sniff'], $f['vars']['fingerprint'], $f['file'], $f['line'], str_replace( '"', "'", substr( $code, 0, 80 ) ) );
			}
		}
	}

	return '' === $yaml ? "# Nothing missing.\n" : "suppressions:\n" . $yaml;
}

function rr_covered_code( RR_Php_File $file, int $line ): string {
	foreach ( rr_suppressions( $file ) as $s ) {
		if ( $s['line'] === $line ) {
			return $file->code_on_line( $s['covered'] );
		}
	}

	return '';
}

// ---------------------------------------------------------------------------
// Command line.
// ---------------------------------------------------------------------------

function rr_central(): string {
	return dirname( __DIR__ );
}

/** @param list<array{rule: string, severity: string, file: string, line: int, message: string}> $findings */
function rr_report( array $findings, string $format, string $prefix ): void {
	if ( 'json' === $format ) {
		echo json_encode( $findings, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE ), "\n";

		return;
	}

	$counts = array();

	foreach ( $findings as $f ) {
		$counts[ $f['severity'] ] = ( $counts[ $f['severity'] ] ?? 0 ) + 1;

		if ( 'github' === $format ) {
			$level = 'notice' === $f['severity'] ? 'notice' : $f['severity'];
			// A message escapes %, CR and LF; a property (file, title) also
			// the ',' and ':' that would end it.
			$esc  = static fn( string $s ): string => str_replace( array( '%', "\r", "\n" ), array( '%25', '%0D', '%0A' ), $s );
			$prop = static fn( string $s ): string => str_replace( array( ',', ':' ), array( '%2C', '%3A' ), $esc( $s ) );
			printf( "::%s file=%s,line=%d,title=%s::%s\n", $level, $prop( $prefix . $f['file'] ), $f['line'], $prop( $f['rule'] ), $esc( $f['message'] ) );
		} else {
			printf( "%s:%d  %s  %s: %s\n", $prefix . $f['file'], $f['line'], $f['severity'], $f['rule'], $f['message'] );
		}
	}

	$by_rule = array_count_values( array_column( $findings, 'rule' ) );
	ksort( $by_rule );

	foreach ( $by_rule as $rule => $n ) {
		printf( "  %-28s %d\n", $rule, $n );
	}

	printf( "%d error(s), %d warning(s), %d notice(s).\n", $counts['error'] ?? 0, $counts['warning'] ?? 0, $counts['notice'] ?? 0 );
}

/** @param list<string> $argv */
function rr_main( array $argv ): int {
	$opts = array(
		'kind'   => '',
		'rules'  => '',
		'repo'   => '.',
		'tree'   => '',
		'format' => 'true' === getenv( 'GITHUB_ACTIONS' ) ? 'github' : 'text',
		'only'   => '',
		'prefix' => '',
	);
	$suggest = false;

	for ( $i = 1; $i < count( $argv ); $i++ ) {
		$arg = $argv[ $i ];

		if ( '--test' === $arg ) {
			return rr_test();
		}

		if ( '--suggest-suppressions' === $arg ) {
			$suggest = true;
			continue;
		}

		if ( '-h' === $arg || '--help' === $arg ) {
			fwrite( STDERR, "Usage: php review-rules.php --kind <kind> | --rules <file> [--repo <dir>] [--tree <dir>] [--format text|github|json] [--only <id,…>] [--prefix <path/>] [--suggest-suppressions]\n       php review-rules.php --test\n" );

			return 0;
		}

		$key = ltrim( $arg, '-' );

		if ( 0 !== strncmp( $arg, '--', 2 ) || ! array_key_exists( $key, $opts ) || ! isset( $argv[ $i + 1 ] ) ) {
			fwrite( STDERR, "Unknown or incomplete option: $arg (--help)\n" );

			return 2;
		}

		$opts[ $key ] = $argv[ ++$i ];
	}

	if ( '' === $opts['rules'] ) {
		if ( ! preg_match( '/^[a-z0-9][a-z0-9-]*$/', $opts['kind'] ) ) {
			fwrite( STDERR, "Name a kind (--kind wordpress-plugin) or a rules file (--rules <file>).\n" );

			return 2;
		}

		$opts['rules'] = rr_central() . '/kinds/' . $opts['kind'] . '/rules.yml';
	}

	$tree = '' === $opts['tree'] ? $opts['repo'] : $opts['tree'];

	foreach ( array( $opts['repo'], $tree ) as $dir ) {
		if ( ! is_dir( $dir ) ) {
			fwrite( STDERR, "Not a directory: $dir\n" );

			return 2;
		}
	}

	try {
		$set = rr_load_rules( $opts['rules'] );

		if ( $suggest ) {
			echo rr_suggest_suppressions( $set, $opts['repo'], $tree );

			return 0;
		}

		$only     = '' === $opts['only'] ? null : array_map( 'trim', explode( ',', $opts['only'] ) );
		$findings = rr_run( $set, $opts['repo'], $tree, $only );
	} catch ( RR_Rules_Error | RR_Yaml_Error $e ) {
		fwrite( STDERR, $e->getMessage() . "\n" );

		return 2;
	}

	rr_report( $findings, $opts['format'], $opts['prefix'] );

	return in_array( 'error', array_column( $findings, 'severity' ), true ) ? 1 : 0;
}

// ---------------------------------------------------------------------------
// Self-test.
// ---------------------------------------------------------------------------

/** A scratch directory with these files, removed by rr_rmdir(). */
function rr_scratch( array $files ): string {
	$dir = sys_get_temp_dir() . '/rr-' . getmypid() . '-' . bin2hex( random_bytes( 4 ) );

	foreach ( $files as $path => $content ) {
		$full = $dir . '/' . $path;

		if ( ! is_dir( dirname( $full ) ) ) {
			mkdir( dirname( $full ), 0777, true );
		}

		file_put_contents( $full, (string) $content );
	}

	if ( ! is_dir( $dir ) ) {
		mkdir( $dir, 0777, true );
	}

	return $dir;
}

function rr_rmdir( string $dir ): void {
	$items = new RecursiveIteratorIterator( new RecursiveDirectoryIterator( $dir, FilesystemIterator::SKIP_DOTS ), RecursiveIteratorIterator::CHILD_FIRST );

	foreach ( $items as $item ) {
		$item->isDir() ? rmdir( (string) $item ) : unlink( (string) $item );
	}

	rmdir( $dir );
}

/** The files of one fixture: a string is one file, a map is path => content. */
function rr_fixture_files( array $rule, $fixture ): array {
	if ( is_array( $fixture ) ) {
		return $fixture;
	}

	return array( ( 'repo' === $rule['scope'] && 'forbidden-config' === $rule['type'] ? 'phpcs.xml.dist' : 'fixture.php' ) => (string) $fixture );
}

/** Every rule's fixtures in one rules file: the failing ones trip it, the passing ones do not. */
function rr_test_fixtures( string $path, int &$cases ): int {
	$failed = 0;

	try {
		$set = rr_load_rules( $path );
	} catch ( RR_Rules_Error $e ) {
		printf( "FAIL %s: %s\n", $path, $e->getMessage() );

		return 1;
	}

	foreach ( $set['rules'] as $rule ) {
		foreach ( array( 'fail' => true, 'pass' => false ) as $kind => $should ) {
			foreach ( (array) $rule['fixtures'][ $kind ] as $n => $fixture ) {
				++$cases;
				$dir = rr_scratch( rr_fixture_files( $rule, $fixture ) );

				try {
					$found = rr_run( $set, $dir, $dir, array( $rule['id'] ) );
				} catch ( Throwable $e ) {
					$found = array();
					printf( "FAIL %s %s fixture %d: %s\n", $rule['id'], $kind, $n + 1, $e->getMessage() );
					++$failed;
					rr_rmdir( $dir );
					continue;
				}

				rr_rmdir( $dir );

				if ( ( array() !== $found ) !== $should ) {
					++$failed;
					printf( "FAIL %s: %s fixture %d %s\n", $rule['id'], $kind, $n + 1, $should ? 'did not trip the rule' : 'tripped it: ' . $found[0]['message'] );
				}
			}
		}
	}

	return $failed;
}

function rr_test(): int {
	$failed = 0;
	$cases  = 0;
	$check  = static function ( string $name, bool $ok, string $detail = '' ) use ( &$failed, &$cases ): void {
		++$cases;

		if ( ! $ok ) {
			++$failed;
			printf( "FAIL %s%s\n", $name, '' === $detail ? '' : ": $detail" );
		}
	};

	// The YAML subset.
	$yaml = <<<'YAML'
# a comment
name: plain text # trailing comment
quoted: 'it''s \d+'
double: "a\tb \"c\""
number: 7
float: 1.5
yes: true
nothing: null
list: [a, 'b, c', "d"]
empty: []
nested:
  inner: 1
  deeper:
    - x
    - y
items:
  - id: one
    when:
      below: 100
  - id: two
    text: |
      line one
        indented
      line three
    folded: >-
      folded
      text

      paragraph
  -
    id: three
same-indent:
- a
- b
YAML;

	try {
		$got = RR_Yaml::parse( $yaml );
		$want = array(
			'name'        => 'plain text',
			'quoted'      => "it's \\d+",
			'double'      => "a\tb \"c\"",
			'number'      => 7,
			'float'       => 1.5,
			'yes'         => true,
			'nothing'     => null,
			'list'        => array( 'a', 'b, c', 'd' ),
			'empty'       => array(),
			'nested'      => array(
				'inner'  => 1,
				'deeper' => array( 'x', 'y' ),
			),
			'items'       => array(
				array(
					'id'   => 'one',
					'when' => array( 'below' => 100 ),
				),
				array(
					'id'     => 'two',
					'text'   => "line one\n  indented\nline three\n",
					'folded' => "folded text\nparagraph",
				),
				array( 'id' => 'three' ),
			),
			'same-indent' => array( 'a', 'b' ),
		);
		$check( 'yaml: the subset reads as YAML does', $got === $want, json_encode( $got ) );
	} catch ( RR_Yaml_Error $e ) {
		$check( 'yaml: the subset reads as YAML does', false, $e->getMessage() );
	}

	foreach ( array(
		'an anchor'           => "a: &x 1\n",
		'a flow map'          => "a: { b: 1 }\n",
		'a tab'               => "a:\n\tb: 1\n",
		'a duplicate key'     => "a: 1\na: 2\n",
		'an unclosed quote'   => "a: 'x\n",
		'bad indentation'     => "a:\n    b: 1\n  c: 2\n",
		'an unclosed list'    => "a: [x, y\n",
	) as $name => $bad ) {
		try {
			RR_Yaml::parse( $bad );
			$check( "yaml: refuses $name", false, 'parsed' );
		} catch ( RR_Yaml_Error $e ) {
			$check( "yaml: refuses $name", true );
		}
	}

	// Against a real YAML reader, when one is installed: every rules file of
	// every kind must read the same through the subset.
	$python = trim( (string) shell_exec( 'command -v python3 2>/dev/null' ) );
	$pyyaml = '' !== $python && '1' === trim( (string) shell_exec( 'python3 -c "import yaml; print(1)" 2>/dev/null' ) );
	$yq     = '' !== trim( (string) shell_exec( 'command -v yq 2>/dev/null' ) );

	foreach ( glob( rr_central() . '/kinds/*/*.yml' ) ?: array() as $file ) {
		if ( $yq ) {
			$json = shell_exec( 'yq -o=json . ' . escapeshellarg( $file ) . ' 2>/dev/null' );
		} elseif ( $pyyaml ) {
			$json = shell_exec( 'python3 -c "import json,sys,yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))" ' . escapeshellarg( $file ) . ' 2>/dev/null' );
		} else {
			echo "skip yaml cross-check of $file (no yq or PyYAML)\n";
			continue;
		}

		try {
			$ours = RR_Yaml::parse( (string) file_get_contents( $file ) );
			$theirs = json_decode( (string) $json, true );
			$check( 'yaml: ' . basename( dirname( $file ) ) . '/' . basename( $file ) . ' reads the same as a YAML library', json_encode( $ours ) === json_encode( $theirs ), 'they differ' );
		} catch ( RR_Yaml_Error $e ) {
			$check( 'yaml: ' . $file, false, $e->getMessage() );
		}
	}

	// The PHP adapter.
	$file  = new RR_Php_File( 'a.php', "<?php\n\\add_menu_page( 'a', 'b' );\nNs\\add_menu_page( 1 );\n\$o->add_menu_page( 2 );\nfunction add_menu_page() {}\n\$s = 'add_menu_page( 3 )';\n" );
	$names = array_column( $file->calls(), 'name' );
	$check( 'php: a fully qualified call is a call', in_array( 'add_menu_page', $names, true ), implode( ',', $names ) );
	$check( 'php: a qualified call keeps its namespace', in_array( 'ns\\add_menu_page', $names, true ), implode( ',', $names ) );
	$check( 'php: a method, a declaration and a string are not calls', 2 === count( $names ), implode( ',', $names ) );

	$file = new RR_Php_File( 'a.php', "<?php\nf( 'a', array( 1, 2 ), position: 5, \$x /* c */ );\n" );
	$args = $file->args( $file->calls()[0]['paren'] );
	$check( 'php: arguments split at their own depth', 4 === count( $args ) && 'array( 1, 2 )' === $args[1]['text'] && 'position' === $args[2]['name'] && '5' === $args[2]['text'] && '$x' === $args[3]['text'], json_encode( $args ) );

	$file = new RR_Php_File( 'a.php', "<?php\nadd_action( 'wp_ajax_' . \$name, 'x' );\nadd_action( \"admin_post_{\$a}\", 'x' );\n" );
	$hooks = array();

	foreach ( $file->calls() as $call ) {
		$a       = $file->args( $call['paren'] );
		$hooks[] = $file->literal( $a[0]['from'], $a[0]['to'] );
	}

	$check( 'php: a hook name built at runtime reads as a glob', array( 'wp_ajax_*', 'admin_post_*' ) === $hooks, implode( ',', $hooks ) );

	$code = <<<'PHP'
<?php
class Plugin_Admin {
	public function __construct() {
		add_action( 'wp_ajax_a', array( $this, 'a' ) );
		add_action( 'wp_ajax_b', [ __CLASS__, 'b' ] );
		add_action( 'wp_ajax_c', 'Plugin_Admin::c' );
		add_action( 'wp_ajax_d', [ self::class, 'd' ] );
		add_action( 'wp_ajax_e', $this->a( ... ) );
	}
	public function a() { check_ajax_referer( 'a' ); }
	public static function b() {}
	public static function c() {}
	public static function d() {}
}
function plugin_f() {}
add_action( 'wp_ajax_f', 'plugin_f' );
add_action( 'wp_ajax_g', function () { $x = 1; } );
add_action( 'wp_ajax_h', static fn() => check_ajax_referer( 'h' ) );
PHP;
	$adapter  = new RR_Php_Adapter( array( 'a.php' => $code ) );
	$file     = $adapter->files['a.php'];
	$resolved = array();

	foreach ( $file->calls() as $call ) {
		if ( 'add_action' !== $call['name'] ) {
			continue;
		}

		$a          = $file->args( $call['paren'] );
		$cb         = $adapter->callback( $file, $a[1], $call['index'] );
		$body       = null === $cb ? null : $adapter->resolve( $cb );
		$resolved[] = null === $body ? '-' : ( $cb['name'] . ':' . $file->text( $body['open'], $body['close'] ) );
	}

	$check(
		'php: every way of naming a callback resolves to its body',
		array( "a:{ check_ajax_referer( 'a' ); }", 'b:{}', 'c:{}', 'd:{}', "a:{ check_ajax_referer( 'a' ); }", 'plugin_f:{}', '{closure}:{ $x = 1; }', "{closure}:=> check_ajax_referer( 'h' )" ) === $resolved,
		implode( ' | ', $resolved )
	);

	$file = new RR_Php_File( 'a.php', "<?php\necho 1; // phpcs:ignore A.B.C, D.E -- why\n\n// phpcs:disable F.G\n\n  \$x  =  1;\n// phpcs:ignore\nfoo();\n// phpcs:ignoreFile\n" );
	$sup  = rr_suppressions( $file );
	$check( 'php: suppressions, their checks and the line they cover', 3 === count( $sup ) && array( 'A.B.C', 'D.E' ) === $sup[0]['sniffs'] && array( 'F.G' ) === $sup[1]['sniffs'] && 6 === $sup[1]['covered'] && array( '*' ) === $sup[2]['sniffs'], json_encode( $sup ) );
	$check( 'php: the fingerprint is the covered code and the two code lines after it, whitespace collapsed', rr_fingerprint( array( '$x = 1;', 'foo();' ) ) === $sup[1]['fingerprint'], $sup[1]['fingerprint'] );

	$same = "<?php\n// phpcs:disable A.B -- why\n\$in = f( \$g );\nq( 1 );\n// phpcs:enable\n\n// phpcs:disable A.B -- why\n\$in = f( \$g );\nq( 2 );\n// phpcs:enable\n";
	$sup  = rr_suppressions( new RR_Php_File( 'a.php', $same ) );
	$check( 'php: identical blocks in front of different code have different fingerprints', 2 === count( $sup ) && $sup[0]['fingerprint'] !== $sup[1]['fingerprint'], json_encode( $sup ) );

	// The rules files: one that is wrong is refused with its reason.
	foreach ( array(
		'no fixtures'      => "rules:\n  - id: a\n    type: comment\n    severity: error\n    message: m\n    source: s\n    pattern: x\n",
		'an unknown type'  => "rules:\n  - id: a\n    type: magic\n    severity: error\n    message: m\n    source: s\n    fixtures: { }\n",
		'no source'        => "rules:\n  - id: a\n    type: comment\n    severity: error\n    message: m\n    pattern: x\n",
		'a bad regex'      => "rules:\n  - id: a\n    type: comment\n    severity: error\n    message: m\n    source: s\n    pattern: '('\n    fixtures:\n      fail: [x]\n      pass: [y]\n",
		'a bad writes'     => "rules:\n  - id: a\n    type: hook-callback\n    severity: error\n    message: m\n    source: s\n    hooks: ['admin_post_*']\n    require:\n      - calls: [check_admin_referer]\n        before-first: superglobal-read\n        when-no-read: pass\n        writes: ['(']\n    fixtures:\n      fail: [x]\n      pass: [y]\n",
	) as $name => $bad ) {
		$dir = rr_scratch( array( 'rules.yml' => $bad ) );

		try {
			rr_load_rules( $dir . '/rules.yml' );
			$check( "rules: refuses $name", false, 'loaded' );
		} catch ( RR_Rules_Error $e ) {
			$check( "rules: refuses $name", true );
		}

		rr_rmdir( $dir );
	}

	// The command line: exit codes, the shipped tree, the prefix.
	$rules = "exclude: ['vendor/**']\nrules:\n  - id: no-x\n    type: forbidden-call\n    severity: error\n    functions: [x]\n    message: 'x() is called'\n    source: test\n    fixtures:\n      fail: [\"<?php x();\"]\n      pass: [\"<?php y();\"]\n";
	$dir   = rr_scratch(
		array(
			'rules.yml'     => $rules,
			'src/a.php'     => "<?php\nx();\n",
			'vendor/b.php'  => "<?php\nx();\n",
		)
	);
	ob_start();
	$exit = rr_main( array( 'review-rules.php', '--rules', $dir . '/rules.yml', '--repo', $dir, '--format', 'text', '--prefix', 'p/' ) );
	$out  = (string) ob_get_clean();
	$check( 'cli: an error exits 1, names the file with its prefix, skips what is excluded', 1 === $exit && false !== strpos( $out, 'p/src/a.php:2' ) && false === strpos( $out, 'vendor' ), "exit $exit: $out" );

	// exclude-checkout: skipped on the checkout, read on a shipped tree.
	$both = rr_scratch(
		array(
			'rules.yml'          => "exclude-checkout: ['**/build/**']\n" . $rules,
			'build/c.php'        => "<?php\nx();\n",
			'ship/build/c.php'   => "<?php\nx();\n",
		)
	);
	ob_start();
	$on_checkout = rr_main( array( 'review-rules.php', '--rules', $both . '/rules.yml', '--repo', $both, '--format', 'text', '--only', 'no-x' ) );
	$said_checkout = (string) ob_get_clean();
	ob_start();
	$on_tree = rr_main( array( 'review-rules.php', '--rules', $both . '/rules.yml', '--repo', $both, '--tree', $both . '/ship', '--format', 'text', '--only', 'no-x' ) );
	$said_tree = (string) ob_get_clean();
	$check( 'exclude-checkout: skipped on the checkout, read on a shipped tree', false === strpos( $said_checkout, 'build/c.php' ) && 1 === $on_tree && false !== strpos( $said_tree, 'build/c.php' ), "checkout $on_checkout: $said_checkout | tree $on_tree: $said_tree" );
	rr_rmdir( $both );
	ob_start();
	$exit = rr_main( array( 'review-rules.php', '--rules', $dir . '/rules.yml', '--repo', $dir, '--tree', $dir . '/vendor', '--format', 'json' ) );
	$out  = (string) ob_get_clean();
	$check( 'cli: --tree is what the code rules read', 1 === $exit && false !== strpos( $out, '"b.php"' ), "exit $exit: $out" );
	rr_rmdir( $dir );

	// Every kind's rules, against their own fixtures.
	$packs = glob( rr_central() . '/kinds/*/rules.yml' ) ?: array();
	$check( 'packs: at least one kind has rules', array() !== $packs );

	foreach ( $packs as $path ) {
		$failed += rr_test_fixtures( $path, $cases );
	}

	printf( "%s: %d case(s), %d failed.\n", 0 === $failed ? 'ok' : 'FAILED', $cases, $failed );

	return 0 === $failed ? 0 : 1;
}

if ( PHP_SAPI === 'cli' && realpath( (string) ( $argv[0] ?? '' ) ) === __FILE__ ) {
	exit( rr_main( $argv ) );
}
