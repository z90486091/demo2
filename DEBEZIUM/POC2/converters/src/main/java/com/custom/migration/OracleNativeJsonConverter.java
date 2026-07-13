package com.custom.migration;

import io.debezium.spi.converter.CustomConverter;
import io.debezium.spi.converter.RelationalColumn;
import org.apache.kafka.connect.data.SchemaBuilder;
import java.util.Properties;

// The generic types must be defined by the SPI
public class OracleNativeJsonConverter implements CustomConverter<SchemaBuilder, RelationalColumn> {

    @Override
    public void configure(Properties props) {
        // No configuration properties needed
    }

    @Override
    public void converterFor(RelationalColumn column, ConverterRegistration<SchemaBuilder> registration) {
        if ("JSON".equalsIgnoreCase(column.typeName())) {
            registration.register(SchemaBuilder.string().optional(), value -> {
                if (value == null) {
                    return null;
                }
                if (value instanceof byte[]) {
                    return new String((byte[]) value);
                }
                return value.toString();
            });
        }
    }
}
