-- code_short_labels is hand-maintained; a new code would otherwise fall back to its long label.
select l.dimension, l.code
from {{ ref('eurostat_code_labels') }} as l
left join {{ ref('code_short_labels') }} as s on s.dimension = l.dimension and s.code = l.code
where l.dimension not in ('geo', 'status') and s.code is null
