FROM pgvector/pgvector:pg16

COPY init.sh /docker-entrypoint-initdb.d/

RUN sed -i 's/\r$//' /docker-entrypoint-initdb.d/init.sh \
	&& chmod +x /docker-entrypoint-initdb.d/init.sh