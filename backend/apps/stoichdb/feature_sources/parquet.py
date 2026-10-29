"""Typed Core Parquet semantics and exact, verified rollback serialization."""
import base64
import pyarrow as pa
import pyarrow.csv as pc
import pyarrow.parquet as pq
from .projection import ProjectionError

def schema_for(source):
    encoded=source.record['receipt_json'].get('arrow_schema_base64')
    if not encoded:raise ProjectionError('Verified legacy Parquet schema missing')
    return pa.ipc.read_schema(pa.BufferReader(base64.b64decode(encoded)))

def typed_batches(source,columns=None):
    schema=schema_for(source)
    wanted=schema.names if columns is None else [name for name in columns if name in schema.names]
    if not wanted:return
    with source.open_binary() as stream:
        reader=pc.open_csv(stream,read_options=pc.ReadOptions(use_threads=False),
            parse_options=pc.ParseOptions(newlines_in_values=True),
            convert_options=pc.ConvertOptions(include_columns=wanted,
                column_types={field.name:field.type for field in schema},strings_can_be_null=False,null_values=[]))
        try:
            yield from reader
        finally:reader.close()

def recover(source,output_path):
    proof=source.record['receipt_json']
    if not proof.get('parquet_recovery_match'):raise ProjectionError('Exact Parquet recovery has not been verified')
    settings=proof['parquet_recovery']
    if pa.__version__!=settings['pyarrow_version']:raise ProjectionError('Recovery requires the proven Arrow writer version')
    chunking=settings.get('input_chunks','coalesced_row_groups')
    if chunking not in {'coalesced_row_groups','csv_blocks'}:raise ProjectionError('Unproven Parquet input chunking recipe')
    schema=schema_for(source);groups=settings['row_group_sizes'];batches=iter(typed_batches(source));pending=[];pending_rows=0
    try:
        with pq.ParquetWriter(output_path,schema,compression=settings['compression']) as writer:
            for count in groups:
                while pending_rows<count:
                    try:batch=next(batches)
                    except StopIteration as exc:raise ProjectionError('Full cannot restore Parquet row groups') from exc
                    pending.append(batch);pending_rows+=batch.num_rows
                table=pa.Table.from_batches(pending,schema=schema)
                selected=table.slice(0,count)
                if chunking=='coalesced_row_groups':selected=selected.combine_chunks()
                writer.write_table(selected,row_group_size=count)
                remainder=table.slice(count);pending=remainder.to_batches();pending_rows=remainder.num_rows
            if pending_rows or next(batches,None) is not None:raise ProjectionError('Full produces additional Parquet Core rows')
    finally:batches.close()
